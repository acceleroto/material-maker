extends Node

# --serve: long-running JSON-RPC mode (used by parse_args.gd).
#
# Reads one JSON request per line on stdin:   {"id": 1, "method": "load", "params": {"path": "/abs/x.ptex"}}
# and prints one JSON response per line:      {"mm_rpc": 1, "id": 1, "ok": true, "result": {...}, "warnings": [...]}
#                                          or {"mm_rpc": 1, "id": 1, "ok": false, "error": {"code": "...", "message": "..."}}
# Engine code also prints to stdout: clients must ignore lines that are not JSON objects with "mm_rpc".
# Our own log messages go to stderr. Requests run one at a time, in order. stdin EOF quits (exit 0).
# The server keeps one graph loaded; edits go through MMGenGraph methods (add_generator,
# connect_children, set_parameter...), never through the JSON.

const PROTOCOL_VERSION : int = 1

# Lines up to this size are read in one piece
const STDIN_BUFFER_SIZE : int = 1 << 22
# OS.read_string_from_stdin() returns "" both for an empty line and at EOF (immediately, forever):
# this many empty reads in a row mean that stdin is closed
const EOF_EMPTY_READS : int = 64

# cli_inspect.gd exit codes -> error codes
const ERROR_CODES : Dictionary = { 1: "bad_params", 2: "load_failed", 3: "render_failed", 4: "invalid" }

const METHODS : Array[String] = [ "load", "save", "list_nodes", "describe_node", "add_node", "remove_node",
		"connect", "disconnect", "set_param", "get_graph", "validate", "render_output", "render_preview",
		"export", "shutdown" ]
# Methods that need a loaded graph
const GRAPH_METHODS : Array[String] = [ "save", "add_node", "remove_node", "connect", "disconnect", "set_param",
		"get_graph", "validate", "render_output", "render_preview", "export" ]

const DEFAULT_TARGET : String = "Unity/URP"
# Parameter types whose values are serialized objects ({"type": "Gradient", ...})
const OBJECT_PARAMETER_TYPES : Array[String] = [ "gradient", "curve", "polygon", "polyline", "splines", "pixels", "lattice" ]

# Host interface used by cli_inspect.gd / cli_preview.gd (reset for every request)
var exit_code : int = 0
var errors : PackedStringArray = PackedStringArray()
var warnings : PackedStringArray = PackedStringArray()
var error_code : String = ""

var inspect : Node = null
var preview : Node = null
var graph : MMGenBase = null
var graph_path : String = ""
var library_manager : Node = null
var env_manager : Node = null

var reader : Thread = null
var queue : Array[String] = []
var busy : bool = false
var stdin_closed : bool = false
var quitting : bool = false


func show_error(message : String, code : int = 1) -> void:
	printerr("ERROR: "+message)
	errors.append(message)
	exit_code = maxi(exit_code, code)
	if error_code == "":
		error_code = ERROR_CODES.get(code, "error")

func show_warning(message : String) -> void:
	printerr("WARNING: "+message)
	warnings.append(message)

# An error with a server specific code
func fail(code : String, message : String) -> void:
	if error_code == "":
		error_code = code
	show_error(message, 1)

func run(_host : Node) -> void:
	inspect = preload("res://cli_inspect.gd").new()
	inspect.host = self
	add_child(inspect)
	preview = preload("res://cli_preview.gd").new()
	add_child(preview)
	var has_device : bool = await inspect.wait_for_rendering_device()
	if not has_device:
		printerr("WARNING: no rendering device (headless?), render methods will fail")
	reader = Thread.new()
	reader.start(read_stdin)
	respond(null, true, { ready=true, version=PROTOCOL_VERSION, pid=OS.get_process_id(), rendering_device=has_device, methods=METHODS }, {})

# Runs in the reader thread
func read_stdin() -> void:
	var empty_reads : int = 0
	while true:
		var line : String = OS.read_string_from_stdin(STDIN_BUFFER_SIZE)
		if line.strip_edges() == "":
			empty_reads += 1
			if empty_reads >= EOF_EMPTY_READS:
				call_deferred("on_stdin_closed")
				return
			continue
		empty_reads = 0
		call_deferred("on_line", line)

func on_line(line : String) -> void:
	queue.append(line)
	if not busy:
		process_queue()

func on_stdin_closed() -> void:
	printerr("stdin closed, quitting")
	stdin_closed = true
	if not busy:
		finish(0)

func process_queue() -> void:
	busy = true
	while not queue.is_empty() and not quitting:
		await handle_line(queue.pop_front())
	busy = false
	if stdin_closed and not quitting:
		finish(0)

func finish(code : int) -> void:
	if quitting:
		return
	quitting = true
	if graph != null:
		remove_child(graph)
		graph.free()
		graph = null
	if env_manager != null:
		env_manager.free()
		env_manager = null
	get_tree().quit(code)

func respond(id : Variant, ok : bool, result : Variant, error : Dictionary) -> void:
	var response : Dictionary = { mm_rpc=PROTOCOL_VERSION, id=id, ok=ok }
	if ok:
		response.result = result if result != null else {}
	else:
		response.error = error
	if not warnings.is_empty():
		response.warnings = Array(warnings)
	print(JSON.stringify(inspect.to_json_safe(response)))

# Checks the shape of a request. Returns { id, method, params, error } (error: "" if fine).
static func parse_request(data : Variant) -> Dictionary:
	var rv : Dictionary = { id=null, method="", params={}, error="" }
	if not data is Dictionary:
		rv.error = "a request must be a JSON object"
		return rv
	rv.id = data.get("id", null)
	if not data.get("method", null) is String or data.method == "":
		rv.error = "missing \"method\" (a string)"
		return rv
	rv.method = data.method
	var params : Variant = data.get("params", null)
	if params == null:
		params = {}
	if not params is Dictionary:
		rv.error = "\"params\" must be a JSON object"
		return rv
	rv.params = params
	return rv

func handle_line(line : String) -> void:
	exit_code = 0
	errors = PackedStringArray()
	warnings = PackedStringArray()
	error_code = ""
	var json : JSON = JSON.new()
	if json.parse(line) != OK:
		respond(null, false, null, { code="parse_error", message="invalid JSON: %s (line %d)" % [ json.get_error_message(), json.get_error_line() ] })
		return
	var request : Dictionary = parse_request(json.data)
	if request.error != "":
		respond(request.id, false, null, { code="bad_request", message=request.error })
		return
	var start : int = Time.get_ticks_msec()
	var result : Variant = null
	if not METHODS.has(request.method):
		fail("unknown_method", "unknown method %s (available: %s)" % [ request.method, ", ".join(METHODS) ])
	elif GRAPH_METHODS.has(request.method) and graph == null:
		fail("no_graph", "no graph loaded (call load first)")
	else:
		result = await call("m_"+request.method, request.params)
		if errors.is_empty() and not result is Dictionary:
			# A script error aborts the method without reporting anything
			fail("internal", "%s failed (script error? see stderr)" % request.method)
	if errors.is_empty():
		result.seconds = (Time.get_ticks_msec()-start)/1000.0
		respond(request.id, true, result, {})
	else:
		var error : Dictionary = { code=error_code, message="; ".join(errors) }
		if errors.size() > 1:
			error.errors = Array(errors)
		respond(request.id, false, null, error)
	if request.method == "shutdown" and errors.is_empty():
		finish(0)

# Parameter helpers

static func param_string(params : Dictionary, key : String, default : String = "") -> String:
	var v : Variant = params.get(key, null)
	return v if v is String else default

func require_string(params : Dictionary, key : String) -> String:
	var v : Variant = params.get(key, null)
	if not v is String or v == "":
		fail("bad_params", "missing \"%s\" (a string)" % key)
		return ""
	return v

func require_absolute_path(params : Dictionary, key : String, required : bool = true) -> String:
	var v : Variant = params.get(key, null)
	if v == null and not required:
		return ""
	if not v is String or v == "":
		fail("bad_params", "missing \"%s\" (an absolute path)" % key)
		return ""
	if not v.is_absolute_path():
		fail("bad_params", "\"%s\" must be an absolute path (got %s)" % [ key, v ])
		return ""
	return v

static func is_number(v : Variant) -> bool:
	return v is int or v is float

func optional_int(params : Dictionary, key : String, default : int, min_value : int, max_value : int) -> int:
	var v : Variant = params.get(key, null)
	if v == null:
		return default
	if not (v is int or v is float) or int(v) != v or v < min_value or v > max_value:
		fail("bad_params", "\"%s\" must be an integer in %d..%d (got %s)" % [ key, min_value, max_value, JSON.stringify(v) ])
		return default
	return int(v)

# Converts a JSON value to the value stored for a parameter definition.
# Returns { value, error } (error: "" if fine).
static func coerce_parameter(def : Dictionary, v : Variant) -> Dictionary:
	var type : String = def.get("type", "")
	var label : String = def.get("name", "?")
	match type:
		"float":
			if v is int or v is float:
				return { value=float(v), error="" }
			if v is String and v.is_valid_float():
				return { value=v.to_float(), error="" }
			# Strings are pasted into the shader as GLSL: only accept expressions of MM variables
			if v is String and (v.contains("$") or v.contains("rnd")):
				return { value=v, error="" }
			return { value=null, error="%s is a float (a number, or an expression of $ variables such as \"$time*0.1\"), got %s" % [ label, JSON.stringify(v) ] }
		"enum":
			var values : Array = def.get("values", [])
			if v is String:
				for i in values.size():
					if values[i] is Dictionary and (str(values[i].get("name", "")).to_lower() == v.to_lower() or str(values[i].get("value", "")) == v):
						return { value=i, error="" }
			elif (v is int or v is float) and int(v) == v and v >= 0 and v < values.size():
				return { value=int(v), error="" }
			var names : PackedStringArray = PackedStringArray()
			for i in values.size():
				names.append("%d=%s" % [ i, values[i].get("name", "?") if values[i] is Dictionary else "?" ])
			return { value=null, error="%s is an enum (%s), got %s" % [ label, ", ".join(names), JSON.stringify(v) ] }
		"size":
			var first : int = int(def.get("first", 0))
			var last : int = int(def.get("last", 13))
			if (v is int or v is float) and int(v) == v and v >= first and v <= last:
				return { value=int(v), error="" }
			return { value=null, error="%s is a size (integer %d..%d, size = 2^value), got %s" % [ label, first, last, JSON.stringify(v) ] }
		"boolean":
			if v is bool:
				return { value=v, error="" }
			if (v is int or v is float) and (v == 0 or v == 1):
				return { value=(v == 1), error="" }
			return { value=null, error="%s is a boolean, got %s" % [ label, JSON.stringify(v) ] }
		"color":
			if v is Dictionary and v.has("r") and v.has("g") and v.has("b"):
				return { value=Color(float(v.r), float(v.g), float(v.b), float(v.get("a", 1.0))), error="" }
			if v is Array and (v.size() == 3 or v.size() == 4):
				return { value=Color(float(v[0]), float(v[1]), float(v[2]), float(v[3]) if v.size() == 4 else 1.0), error="" }
			if v is String and Color.html_is_valid(v):
				return { value=Color.html(v), error="" }
			return { value=null, error="%s is a color ({r,g,b,a} 0..1, [r,g,b(,a)] or \"#rrggbb\"), got %s" % [ label, JSON.stringify(v) ] }
	if OBJECT_PARAMETER_TYPES.has(type):
		if v is Dictionary and v.has("type"):
			return { value=MMType.deserialize_value(v), error="" }
		return { value=null, error="%s is a %s (an object with \"type\", as in get_graph full=true), got %s" % [ label, type, JSON.stringify(v) ] }
	return { value=v, error="" }

# Graph helpers

func find_gen(path : String, key : String = "node") -> MMGenBase:
	var node : Node = graph.get_node_or_null(NodePath(path)) if path != "" else null
	if node is MMGenBase:
		return node
	var parent : Node = graph.get_node_or_null(NodePath(path.get_base_dir())) if path.contains("/") else graph
	var names : PackedStringArray = PackedStringArray()
	if parent != null:
		for c in parent.get_children():
			if c is MMGenBase:
				names.append(c.name)
	names.sort()
	fail("unknown_node", "%s: no node %s (nodes %s: %s)" % [ key, path, "in "+path.get_base_dir() if path.contains("/") else "at the top level", ", ".join(names) ])
	return null

func find_graph(path : String, key : String) -> MMGenGraph:
	if path == "":
		if graph is MMGenGraph:
			return graph
		fail("bad_params", "the loaded file is not a graph")
		return null
	var gen : MMGenBase = find_gen(path, key)
	if gen != null and not gen is MMGenGraph:
		fail("bad_params", "%s: %s is a %s, not a graph" % [ key, path, gen.get_type() ])
		return null
	return gen

static func gen_type(gen : MMGenBase) -> String:
	return str(gen.model) if gen.model != null else gen.get_type()

static func port_summary(defs : Array) -> Array[Dictionary]:
	var rv : Array[Dictionary] = []
	for i in defs.size():
		var d : Dictionary = defs[i] if defs[i] is Dictionary else {}
		rv.append({ index=i, name=d.get("name", ""), type=d.get("type", "any"), label=d.get("shortdesc", d.get("label", d.get("name", ""))) })
	return rv

static func parameter_values(gen : MMGenBase) -> Dictionary:
	var rv : Dictionary = {}
	for p in gen.get_parameter_defs():
		if p is Dictionary and p.has("name"):
			rv[p.name] = MMType.serialize_value(gen.parameters[p.name]) if gen.parameters.has(p.name) else p.get("default", null)
	return rv

static func node_connections(parent : MMGenGraph, gen_name : String) -> Dictionary:
	var inputs : Array = []
	var outputs : Array = []
	for c : Dictionary in parent.connections:
		if c.to == gen_name:
			inputs.append(c.duplicate())
		if c.from == gen_name:
			outputs.append(c.duplicate())
	return { inputs=inputs, outputs=outputs }

func set_parameters(gen : MMGenBase, values : Dictionary) -> Array:
	var defs : Dictionary = {}
	for p in gen.get_parameter_defs():
		if p is Dictionary and p.has("name"):
			defs[p.name] = p
	var coerced : Dictionary = {}
	for k in values.keys():
		if not defs.has(k):
			var names : Array = defs.keys()
			names.sort()
			fail("unknown_parameter", "%s has no parameter %s (parameters: %s)" % [ gen.name, k, ", ".join(PackedStringArray(names)) ])
			continue
		var c : Dictionary = coerce_parameter(defs[k], values[k])
		if c.error != "":
			fail("bad_value", "%s: %s" % [ gen.name, c.error ])
			continue
		coerced[k] = c.value
	if not errors.is_empty():
		return []
	var changed : Array = []
	for k in coerced.keys():
		var d : Dictionary = defs[k]
		var v : Variant = coerced[k]
		if v is float and ((d.has("min") and v < float(d.min)) or (d.has("max") and v > float(d.max))):
			show_warning("%s.%s = %s is outside the slider range %s..%s" % [ gen.name, k, v, d.get("min"), d.get("max") ])
		var old_value : Variant = MMType.serialize_value(gen.parameters[k]) if gen.parameters.has(k) else null
		gen.set_parameter(k, v)
		changed.append({ name=k, old=old_value, new=MMType.serialize_value(gen.parameters.get(k, v)) })
	return changed

# mm_deps.do_update() awaits buffer renders of the graph's nodes: freeing a node while it renders
# leaves that coroutine waiting forever (and every later render waiting for mm_deps.updated).
# Called before freeing a graph or removing a node.
func settle_renders(timeout_ms : int = 30000) -> void:
	var deadline : int = Time.get_ticks_msec()+timeout_ms
	# Start pending updates (do_update runs deferred), then wait until they are done
	mm_deps.update()
	await get_tree().process_frame
	while mm_deps.updating and Time.get_ticks_msec() < deadline:
		await get_tree().process_frame
	if mm_deps.updating:
		show_warning("renders still running after %d s" % (timeout_ms/1000))

# Methods (m_<name>: params Dictionary -> result Dictionary; errors through fail()/show_error())

func m_load(params : Dictionary) -> Dictionary:
	var path : String = require_absolute_path(params, "path")
	if path == "":
		return {}
	if DirAccess.dir_exists_absolute(path):
		show_error("Cannot load %s (a directory, not a .ptex file)" % path, 2)
		return {}
	var gen : MMGenBase = await mm_loader.load_gen(path)
	if gen == null:
		show_error("Cannot load %s (%s)" % [ path, "not a valid material file" if FileAccess.file_exists(path) else "no such file" ], 2)
		return {}
	if graph != null:
		await settle_renders()
		remove_child(graph)
		graph.free()
	graph = gen
	graph_path = path
	add_child(graph)
	load_warnings(path)
	var material : Node = graph.get_node_or_null("Material")
	var nodes : int = 0
	for c in graph.get_children():
		if c is MMGenBase:
			nodes += 1
	return { path=path, nodes=nodes, material=(material is MMGenMaterial), image_size=material.get_image_size() if material is MMGenMaterial else 0 }

# The loader silently drops nodes of unknown types and connections it cannot make: compare the
# loaded graph with the file and report those, and file parameters naming missing files
func load_warnings(path : String) -> void:
	var rv : Dictionary = { nodes=0, errors=[] as Array[Dictionary], warnings=[] as Array[Dictionary] }
	var data : Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if graph is MMGenGraph and data is Dictionary:
		inspect.check_graph(graph, data, "/", rv)
	inspect.check_files(graph, "/", rv)
	for i : Dictionary in rv.errors + rv.warnings:
		show_warning("%s%s (%s)" % [ "" if i.graph_path == "/" else i.graph_path+": ", i.message, i.code ])

func m_save(params : Dictionary) -> Dictionary:
	var path : String = require_absolute_path(params, "path", false)
	if not errors.is_empty():
		return {}
	if path == "":
		path = graph_path
	if path == "":
		fail("bad_params", "missing \"path\" (the graph was not loaded from a file)")
		return {}
	if not DirAccess.dir_exists_absolute(path.get_base_dir()) and DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		fail("save_failed", "cannot create directory "+path.get_base_dir())
		return {}
	mm_loader.current_project_path = path.get_base_dir()
	var data : Dictionary = graph.serialize()
	mm_loader.current_project_path = ""
	var text : String = JSON.stringify(data, "\t", true)
	var file : FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		fail("save_failed", "cannot write %s (%s)" % [ path, error_string(FileAccess.get_open_error()) ])
		return {}
	file.store_string(text)
	file.close()
	graph.set_meta("file_path", path)
	graph_path = path
	return { path=path, bytes=text.length() }

func m_list_nodes(params : Dictionary) -> Dictionary:
	if library_manager == null:
		library_manager = inspect.create_library_manager()
		await library_manager.libraries_changed
	var listing : Dictionary = await inspect.list_nodes(library_manager)
	var query : String = param_string(params, "query").to_lower()
	var category : String = param_string(params, "category").to_lower()
	if query == "" and category == "":
		return listing
	var items : Array = []
	for i : Dictionary in listing.items:
		if category != "" and i.category.to_lower() != category:
			continue
		if query != "" and not (query in i.type.to_lower() or query in i.display_name.to_lower() or query in i.shortdesc.to_lower() or query in ",".join(PackedStringArray(i.keywords)).to_lower()):
			continue
		items.append(i)
	var types : Array = []
	for t : Dictionary in listing.types:
		if category != "" and t.category.to_lower() != category:
			continue
		if query != "" and not (query in t.type.to_lower() or query in t.label.to_lower() or query in t.shortdesc.to_lower()):
			continue
		types.append(t)
	return { items=items, types=types }

func m_describe_node(params : Dictionary) -> Dictionary:
	var type : String = param_string(params, "type")
	var node_path : String = param_string(params, "node")
	if (type == "") == (node_path == ""):
		fail("bad_params", "give either \"type\" (a node type) or \"node\" (a node of the loaded graph)")
		return {}
	if type != "":
		var d : Dictionary = await inspect.describe_type(type)
		if d.is_empty():
			fail("unknown_type", "unknown node type "+type)
		return d
	if graph == null:
		fail("no_graph", "no graph loaded (call load first)")
		return {}
	var gen : MMGenBase = find_gen(node_path)
	if gen == null:
		return {}
	var rv : Dictionary = {
		node = node_path,
		name = gen.name,
		type = gen_type(gen),
		generator = gen.get_script().get_global_name(),
		label = gen.get_type_name(),
		description = gen.get_description(),
		parameters = inspect.parameter_defs_with_values(gen),
		inputs = port_summary(gen.get_input_defs()),
		outputs = port_summary(gen.get_output_defs()),
		position = gen.position
	}
	if gen.get_parent() is MMGenGraph:
		rv.connections = node_connections(gen.get_parent(), gen.name)
	if gen is MMGenGraph:
		rv.children = gen.get_child_count()
	return rv

func m_add_node(params : Dictionary) -> Dictionary:
	var type : String = require_string(params, "type")
	if type == "":
		return {}
	var parent : MMGenGraph = find_graph(param_string(params, "parent"), "parent")
	if parent == null:
		return {}
	var data : Dictionary = inspect.BUILTIN_DATA[type].duplicate(true) if inspect.BUILTIN_DATA.has(type) else { type=type }
	if not mm_loader.predefined_generators.has(type) and not inspect.BUILTIN_TYPES.has(type):
		fail("unknown_type", "unknown node type %s (see list_nodes)" % type)
		return {}
	var node_name : String = param_string(params, "name")
	if node_name != "":
		if not node_name.is_valid_filename() or node_name.contains("/") or node_name.contains(":") or node_name.contains("."):
			fail("bad_params", "invalid node name "+node_name)
			return {}
		data.name = node_name
	var position : Variant = params.get("position", null)
	if position is Dictionary and is_number(position.get("x")) and is_number(position.get("y")):
		data.node_position = { x=float(position.x), y=float(position.y) }
	elif position is Array and position.size() == 2 and is_number(position[0]) and is_number(position[1]):
		data.node_position = { x=float(position[0]), y=float(position[1]) }
	elif position != null:
		fail("bad_params", "\"position\" must be [x, y] or {\"x\": ..., \"y\": ...}")
		return {}
	else:
		# Right of the rightmost node, so that the graph stays readable in the editor
		var x : float = 0.0
		for c in parent.get_children():
			if c is MMGenBase:
				x = maxf(x, c.position.x+250.0)
		data.node_position = { x=x, y=0.0 }
	var values : Variant = params.get("parameters", {})
	if not values is Dictionary:
		fail("bad_params", "\"parameters\" must be an object")
		return {}
	var gen : MMGenBase = await mm_loader.create_gen(data)
	if gen == null:
		fail("unknown_type", "cannot create a node of type "+type)
		return {}
	if not parent.add_generator(gen):
		gen.free()
		fail("bad_params", "cannot add a %s node here (only one Material node, at the top level)" % type)
		return {}
	var changed : Array = set_parameters(gen, values)
	if not errors.is_empty():
		parent.remove_generator(gen)
		return {}
	for i : Dictionary in inspect.missing_files(gen, ""):
		show_warning(i.message)
	var path : String = (param_string(params, "parent")+"/"+gen.name).trim_prefix("/")
	return { node=path, name=gen.name, type=gen_type(gen), inputs=port_summary(gen.get_input_defs()),
			outputs=port_summary(gen.get_output_defs()), parameters=parameter_values(gen), changed=changed }

func m_remove_node(params : Dictionary) -> Dictionary:
	var node_path : String = require_string(params, "node")
	if node_path == "":
		return {}
	var gen : MMGenBase = find_gen(node_path)
	if gen == null:
		return {}
	var parent : Node = gen.get_parent()
	if gen == graph or not parent is MMGenGraph:
		fail("bad_params", "cannot remove the top level graph")
		return {}
	var removed : Dictionary = node_connections(parent, gen.name)
	await settle_renders()
	if not parent.remove_generator(gen):
		fail("cannot_delete", "%s cannot be deleted" % node_path)
		return {}
	return { removed=node_path, connections_removed=removed.inputs+removed.outputs }

# Finds the two ends of a connection; they must be in the same graph
func connection_ends(params : Dictionary, need_from : bool = true) -> Dictionary:
	var rv : Dictionary = { from=null, to=null, from_port=0, to_port=0, parent=null }
	var to_path : String = require_string(params, "to")
	var from_path : String = param_string(params, "from")
	if need_from and from_path == "":
		require_string(params, "from")
	if not errors.is_empty():
		return rv
	rv.to_port = optional_int(params, "to_port", 0, 0, 1000)
	rv.from_port = optional_int(params, "from_port", 0, 0, 1000)
	rv.to = find_gen(to_path, "to")
	if from_path != "":
		rv.from = find_gen(from_path, "from")
	if not errors.is_empty():
		return rv
	rv.parent = rv.to.get_parent()
	if not rv.parent is MMGenGraph:
		fail("bad_params", "%s is not inside a graph" % to_path)
	elif rv.from != null and rv.from.get_parent() != rv.parent:
		fail("bad_params", "%s and %s are not in the same graph" % [ from_path, to_path ])
	return rv

func m_connect(params : Dictionary) -> Dictionary:
	var ends : Dictionary = connection_ends(params)
	if not errors.is_empty():
		return {}
	var from : MMGenBase = ends.from
	var to : MMGenBase = ends.to
	var parent : MMGenGraph = ends.parent
	var outputs : Array = from.get_output_defs()
	var inputs : Array = to.get_input_defs()
	if ends.from_port >= outputs.size():
		fail("bad_port", "%s has %d output(s), no output %d" % [ from.name, outputs.size(), ends.from_port ])
	if ends.to_port >= inputs.size():
		fail("bad_port", "%s has %d input(s), no input %d" % [ to.name, inputs.size(), ends.to_port ])
	if not errors.is_empty():
		return {}
	var out_type : String = outputs[ends.from_port].get("type", "any") if outputs[ends.from_port] is Dictionary else "any"
	var in_type : String = inputs[ends.to_port].get("type", "any") if inputs[ends.to_port] is Dictionary else "any"
	if not inspect.is_compatible_port_type(out_type, in_type, mm_io_types.types):
		fail("port_type_mismatch", "cannot connect a %s output (%s:%d) to a %s input (%s:%d)" % [ out_type, from.name, ends.from_port, in_type, to.name, ends.to_port ])
		return {}
	var replaced : Variant = null
	for c : Dictionary in parent.connections:
		if c.to == to.name and c.to_port == ends.to_port:
			replaced = c.duplicate()
	if not parent.connect_children(from, ends.from_port, to, ends.to_port):
		fail("connection_rejected", "connection %s:%d -> %s:%d rejected (it would create a loop)" % [ from.name, ends.from_port, to.name, ends.to_port ])
		return {}
	return { connection={ from=from.name, from_port=ends.from_port, to=to.name, to_port=ends.to_port }, replaced=replaced }

func m_disconnect(params : Dictionary) -> Dictionary:
	var ends : Dictionary = connection_ends(params, false)
	if not errors.is_empty():
		return {}
	var to : MMGenBase = ends.to
	var parent : MMGenGraph = ends.parent
	var found : Variant = null
	for c : Dictionary in parent.connections:
		if c.to == to.name and c.to_port == ends.to_port and (ends.from == null or (c.from == ends.from.name and c.from_port == ends.from_port)):
			found = c.duplicate()
			break
	if found == null:
		fail("no_connection", "no connection %sto %s:%d" % [ "from %s:%d " % [ ends.from.name, ends.from_port ] if ends.from != null else "", to.name, ends.to_port ])
		return {}
	parent.disconnect_children_ext(found.from, found.from_port, found.to, to, found.to_port)
	return { removed=found }

func m_set_param(params : Dictionary) -> Dictionary:
	var node_path : String = require_string(params, "node")
	if node_path == "":
		return {}
	var values : Dictionary = {}
	if params.has("params"):
		if not params.params is Dictionary or params.params.is_empty():
			fail("bad_params", "\"params\" must be a non-empty object {name: value}")
			return {}
		values = params.params
	elif params.has("name") and params.has("value"):
		var n : String = require_string(params, "name")
		values[n] = params.value
	else:
		fail("bad_params", "give \"name\" and \"value\", or \"params\": {name: value}")
		return {}
	var gen : MMGenBase = find_gen(node_path)
	if gen == null:
		return {}
	var changed : Array = set_parameters(gen, values)
	if not errors.is_empty():
		return {}
	for i : Dictionary in inspect.missing_files(gen, ""):
		show_warning(i.message)
	return { node=node_path, changed=changed }

func m_get_graph(params : Dictionary) -> Dictionary:
	var g : MMGenGraph = find_graph(param_string(params, "node"), "node")
	if g == null:
		return {}
	if params.get("full", false) == true:
		mm_loader.current_project_path = graph_path.get_base_dir()
		var data : Dictionary = g.serialize()
		mm_loader.current_project_path = ""
		return { path=graph_path, graph=data }
	var nodes : Array = []
	for c in g.get_children():
		if not c is MMGenBase:
			continue
		var n : Dictionary = { name=c.name, type=gen_type(c), parameters=parameter_values(c) }
		if c is MMGenGraph:
			n.graph = true
			n.label = c.get_type_name()
		nodes.append(n)
	var connections : Array = []
	for c : Dictionary in g.connections:
		connections.append(c.duplicate())
	var rv : Dictionary = { path=graph_path, node=param_string(params, "node"), nodes=nodes, connections=connections }
	var material : Node = g.get_node_or_null("Material")
	if material is MMGenMaterial:
		rv.image_size = material.get_image_size()
	return rv

func m_validate(_params : Dictionary) -> Dictionary:
	var rv : Dictionary = { ok=false, nodes=0, outputs_checked=0, errors=[] as Array[Dictionary], warnings=[] as Array[Dictionary] }
	var data : Dictionary = graph.serialize()
	await inspect.validate_gen(graph, data, rv)
	return rv

func render_output_path(params : Dictionary) -> String:
	var output : String = require_absolute_path(params, "output")
	if output != "" and not inspect.RENDER_EXTENSIONS.has(output.get_extension().to_lower()):
		fail("bad_params", "unsupported output file %s (expected %s)" % [ output.get_file(), "/".join(inspect.RENDER_EXTENSIONS) ])
		return ""
	return output

func m_render_output(params : Dictionary) -> Dictionary:
	var node_path : String = require_string(params, "node")
	var output : String = render_output_path(params)
	var port : int = optional_int(params, "port", 0, 0, 1000)
	var size : int = optional_int(params, "size", inspect.RENDER_DEFAULT_SIZE, inspect.RENDER_MIN_SIZE, inspect.RENDER_MAX_SIZE)
	if not errors.is_empty():
		return {}
	if find_gen(node_path) == null:
		return {}
	var rv : Dictionary = { node=node_path, port=port, size=size, file="" }
	if not await inspect.wait_for_rendering_device():
		show_error("no rendering device (headless?), cannot render", 3)
		return {}
	await inspect.render_node(graph, node_path, port, size, output, rv)
	if errors.is_empty() and rv.file == "":
		fail("render_failed", "render_output wrote no file (script error? see stderr)")
	return rv

func m_render_preview(params : Dictionary) -> Dictionary:
	var output : String = render_output_path(params)
	var size : int = optional_int(params, "size", inspect.RENDER_DEFAULT_SIZE, inspect.RENDER_MIN_SIZE, inspect.PREVIEW_MAX_SIZE)
	var env : String = param_string(params, "env", inspect.PREVIEW_DEFAULT_ENV)
	var mesh_param : Variant = params.get("mesh", inspect.PREVIEW_DEFAULT_MESH)
	var mesh_names : Array = mesh_param.to_lower().split("+") if mesh_param is String else (mesh_param if mesh_param is Array else [])
	var meshes : Array[String] = []
	for m in mesh_names:
		if not m is String or not inspect.PREVIEW_MESHES.has(m):
			fail("bad_params", "unknown mesh %s (expected %s, or several joined with +)" % [ m, "|".join(inspect.PREVIEW_MESHES) ])
		elif not meshes.has(m):
			meshes.append(m)
	if meshes.is_empty() and errors.is_empty():
		fail("bad_params", "\"mesh\" must be a string like \"sphere+plane\" or a list of mesh names")
	if not errors.is_empty():
		return {}
	if not await inspect.wait_for_rendering_device():
		show_error("no rendering device (headless?), cannot render", 3)
		return {}
	if env_manager == null:
		env_manager = preview.create_environment_manager()
	var rv : Dictionary = { meshes=meshes, env=env, size=size, file="" }
	await preview.render_gen(inspect, graph, env_manager, meshes, env, size, output, rv)
	if errors.is_empty() and rv.file == "":
		fail("render_failed", "render_preview wrote no file (script error? see stderr)")
	return rv

func m_export(params : Dictionary) -> Dictionary:
	var parse_args : GDScript = preload("res://parse_args.gd")
	var output_dir : String = require_absolute_path(params, "output_dir")
	var target : String = param_string(params, "target", DEFAULT_TARGET)
	var size : int = optional_int(params, "size", 0, 0, inspect.EXPORT_MAX_SIZE)
	var prefix : String = param_string(params, "prefix", graph_path.get_file().get_basename() if graph_path != "" else "material")
	if prefix == "" or prefix.contains("/") or not prefix.is_valid_filename():
		fail("bad_params", "invalid prefix "+prefix)
	var overwrite : bool = params.get("overwrite", true) == true
	if not errors.is_empty():
		return {}
	if not DirAccess.dir_exists_absolute(output_dir) and DirAccess.make_dir_recursive_absolute(output_dir) != OK:
		fail("export_failed", "cannot create output directory "+output_dir)
		return {}
	var rv : Dictionary = { output_dir=output_dir, prefix=prefix, target="", size=0, files=[] as Array[String], deleted=[] as Array[String] }
	var material : MMGenBase = null
	for c in graph.get_children():
		if c is MMGenBase and c.has_method("get_export_profiles"):
			material = c
			break
	if material == null:
		fail("no_material", "the graph has no Material node")
		return {}
	var resolved : Dictionary = parse_args.resolve_target(target, material.get_export_profiles(), true)
	if resolved.error != "":
		fail("bad_params", resolved.error)
		return {}
	rv.target = resolved.target
	rv.size = size if size > 0 else material.get_image_size()
	# In command line mode MM skips files that the editor would ask to overwrite (e.g. .mat)
	if overwrite:
		for f : String in DirAccess.get_files_at(output_dir):
			if f.begins_with(prefix+".") or f.begins_with(prefix+"_"):
				if DirAccess.remove_absolute(output_dir.path_join(f)) == OK:
					rv.deleted.append(output_dir.path_join(f))
	# The Material node and additional export nodes, as in parse_args.gd export_files()
	var gen_stack : Array = [ graph ]
	while not gen_stack.is_empty():
		var c : Node = gen_stack.pop_back()
		gen_stack.append_array(c.get_children())
		if not c.has_method("export_material"):
			continue
		var file_prefix : String = output_dir.path_join(prefix)
		var name_prefix : String = prefix
		var export_target : String = rv.target
		if not c.has_method("get_export_profiles"):
			var file_name : String = c.interpret_file_name(c.parameters.suffix, output_dir)
			name_prefix = file_name.get_file()
			export_target = target
		var before : Dictionary = parse_args.dir_snapshot(output_dir)
		await c.export_material(file_prefix, export_target, size, true)
		rv.files.append_array(parse_args.written_files(output_dir, before, name_prefix))
	# Exporting runs process_shader() on the target's templates, which replaces the Material's preview
	# textures (and deletes their mm_deps buffers): rebuild the preview, or later edits never reach it
	await material.update()
	await settle_renders()
	if rv.files.is_empty():
		fail("export_failed", "the export wrote no files to "+output_dir)
		return {}
	rv.files.sort()
	return rv

func m_shutdown(_params : Dictionary) -> Dictionary:
	return { bye=true }
