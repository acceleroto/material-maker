extends Node

# Command line inspection modes (used by parse_args.gd):
#   --list-nodes [--json]                     node types and add-node menu items
#   --describe-node <type>... | --all [--json] parameters and ports of instantiated generators
#   --validate <file.ptex>... [--json]        missing types, bad connections, shader compile errors

const EXIT_OK : int = 0
const EXIT_BAD_ARGS : int = 1
const EXIT_LOAD : int = 2
const EXIT_INVALID : int = 4

const MODES : Array[String] = [ "--list-nodes", "--describe-node", "--validate" ]

# Same values as the NodeLibraryManager node in material_maker/main_window.tscn
const LIBRARY_MANAGER_SETTINGS : Dictionary = {
	base_lib_name = "Base library",
	base_lib = "root://library/base.json",
	alt_base_lib = "res://material_maker/library/base.json",
	user_lib_name = "User library",
	user_lib = "user://library/user.json",
	config_section = "node_lib",
	base_aliases_file_name = "root://library/aliases.json",
	alt_base_aliases_file_name = "res://material_maker/library/aliases.json",
	user_aliases_file_name = "user://library/aliases.json"
}
const LIBRARY_SECTIONS : PackedStringArray = [ "Simple", "Pattern", "Noise", "Filter", "Transform", "Workflow", "3D", "Miscellaneous" ]

# Generator types handled directly by mm_loader.create_gen (not .mmg files)
const BUILTIN_TYPES : Array[String] = [ "material_export", "buffer", "image", "text", "iterate_buffer", "meshmap", "sdf",
		"ios", "switch", "export", "comment", "webcam", "debug", "reroute", "comment_line", "portal", "graph", "remote" ]

# Data that makes mm_loader.create_gen build the types it only recognizes by their keys
const BUILTIN_DATA : Dictionary = {
	graph = { type="graph", nodes=[], connections=[] },
	remote = { type="remote", widgets=[] },
	ios = { type="ios", ports=[] }
}

# Bare built-in generators whose _ready() fails outside the editor (it needs the main window or
# a material model); their definitions don't depend on it
const DESCRIBE_OUTSIDE_TREE : Array[String] = [ "comment", "comment_line", "material_export" ]


# Types that never take part in shader generation
const NO_SHADER_TYPES : Array[String] = [ "comment", "comment_line", "remote" ]

var host : Node = null


class ShaderErrorCapture:
	extends Object
	var captured : Array[Dictionary] = []
	func on_error(shader : String, error_message : String) -> void:
		captured.append({ shader=shader, error=error_message })


static func parse_inspect_args(args : PackedStringArray) -> Dictionary:
	var rv : Dictionary = { mode = "", types = [] as Array[String], all = false, files = [] as Array[String], json = false, errors = [] as Array[String] }
	var start : int = -1
	for m : String in MODES:
		var index : int = args.find(m)
		if index != -1 and (start == -1 or index < start):
			start = index
	if start == -1:
		rv.errors.append("no mode (expected one of %s)" % ", ".join(MODES))
		return rv
	for i in range(start, args.size()):
		var arg : String = args[i]
		if arg in MODES:
			if rv.mode != "" and rv.mode != arg:
				rv.errors.append("%s and %s cannot be combined" % [ rv.mode, arg ])
			rv.mode = arg
		elif arg == "--json":
			rv.json = true
		elif arg == "--all":
			rv.all = true
		elif arg == "--no-splash":
			pass
		elif arg.begins_with("-"):
			rv.errors.append("unknown option "+arg)
		elif rv.mode == "--describe-node":
			rv.types.append(arg)
		elif rv.mode == "--validate":
			rv.files.append(arg)
		else:
			rv.errors.append("unexpected argument "+arg)
	if not rv.errors.is_empty():
		return rv
	match rv.mode:
		"--describe-node":
			if rv.all and not rv.types.is_empty():
				rv.errors.append("--all cannot be combined with type names")
			elif not rv.all and rv.types.is_empty():
				rv.errors.append("no node type (expected --describe-node <type>... or --describe-node --all)")
		"--validate":
			if rv.files.is_empty():
				rv.errors.append("no input file")
		_:
			if rv.all:
				rv.errors.append("--all is only valid with --describe-node")
	return rv

# Converts engine values (Color, Vector*, objects with serialize()) to JSON compatible data
static func to_json_safe(v : Variant) -> Variant:
	match typeof(v):
		TYPE_DICTIONARY:
			var rv : Dictionary = {}
			for k in v.keys():
				rv[str(k)] = to_json_safe(v[k])
			return rv
		TYPE_ARRAY, TYPE_PACKED_STRING_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_FLOAT32_ARRAY, TYPE_PACKED_FLOAT64_ARRAY:
			var rv : Array = []
			for e in v:
				rv.append(to_json_safe(e))
			return rv
		TYPE_COLOR:
			return { r=to_json_safe(v.r), g=to_json_safe(v.g), b=to_json_safe(v.b), a=to_json_safe(v.a) }
		TYPE_VECTOR2, TYPE_VECTOR2I:
			return { x=to_json_safe(v.x), y=to_json_safe(v.y) }
		TYPE_VECTOR3, TYPE_VECTOR3I:
			return { x=to_json_safe(v.x), y=to_json_safe(v.y), z=to_json_safe(v.z) }
		TYPE_STRING_NAME, TYPE_NODE_PATH:
			return str(v)
		TYPE_OBJECT:
			if v == null:
				return null
			if v.has_method("serialize"):
				return to_json_safe(v.serialize())
			return str(v)
		TYPE_FLOAT:
			# keep integral values as ints in JSON
			if is_finite(v) and v == floorf(v) and absf(v) < 1e15:
				return int(v)
			return v
	return v

static func is_compatible_port_type(from_type : String, to_type : String, io_types : Dictionary) -> bool:
	if from_type == to_type or from_type == "any" or to_type == "any":
		return true
	if not io_types.has(from_type) or not io_types.has(to_type):
		return true
	return io_types[from_type].slot_type == io_types[to_type].slot_type

# Checks connections against port definitions.
# port_defs: node name -> { inputs: Array of port type strings, outputs: Array of port type strings }
# missing: names of nodes that could not be created (connections to them are not reported again)
static func check_connections(connections : Array, port_defs : Dictionary, missing : Array, io_types : Dictionary, graph_path : String) -> Array[Dictionary]:
	var rv : Array[Dictionary] = []
	var fed : Dictionary = {}
	for i in connections.size():
		var c = connections[i]
		if not c is Dictionary or not (c.has("from") and c.has("from_port") and c.has("to") and c.has("to_port")):
			rv.append(issue("bad_connection", graph_path, "", "connections[%d] must have from, from_port, to, to_port" % i))
			continue
		var label : String = "%s:%s -> %s:%s" % [ c.from, port_str(c.from_port), c.to, port_str(c.to_port) ]
		var ok : bool = true
		var types : Dictionary = {}
		for end : Array in [ [ str(c.from), c.from_port, "outputs", "output" ], [ str(c.to), c.to_port, "inputs", "input" ] ]:
			var node_name : String = end[0]
			if missing.has(node_name):
				ok = false
				continue
			if not port_defs.has(node_name):
				rv.append(issue("unknown_node", graph_path, "", "connection %s refers to missing node %s" % [ label, node_name ]))
				ok = false
				continue
			var ports : Array = port_defs[node_name][end[2]]
			var port = end[1]
			if not (port is int or port is float) or int(port) != port or port < 0 or port >= ports.size():
				rv.append(issue("bad_%s_port" % end[3], graph_path, node_name, "connection %s: %s has no %s port %s (it has %d)" % [ label, node_name, end[3], port_str(port), ports.size() ]))
				ok = false
				continue
			types[end[3]] = ports[int(port)]
		if not ok:
			continue
		var key : String = "%s:%d" % [ c.to, int(c.to_port) ]
		if fed.has(key):
			rv.append(issue("input_multiply_connected", graph_path, str(c.to), "input %s is fed by both %s and %s:%d" % [ key, fed[key], c.from, int(c.from_port) ]))
		else:
			fed[key] = "%s:%d" % [ c.from, int(c.from_port) ]
		if not is_compatible_port_type(types.output, types.input, io_types):
			rv.append(issue("port_type_mismatch", graph_path, str(c.to), "connection %s connects a %s output to a %s input" % [ label, types.output, types.input ]))
	return rv

static func port_str(port : Variant) -> String:
	if port is float and port == floorf(port):
		return str(int(port))
	return str(port)

static func issue(code : String, graph_path : String, node_name : String, message : String) -> Dictionary:
	return { code=code, graph_path=graph_path, node=node_name, message=message }

# Splits a glslang error message into located messages, using the "// #section: node (id)"
# markers the shader generator puts in the code (same format as shader_error_handler.gd)
static func parse_shader_error(shader : String, error_message : String) -> Array[Dictionary]:
	var rv : Array[Dictionary] = []
	var code_lines : PackedStringArray = shader.split("\n")
	var regex : RegEx = RegEx.create_from_string("// #(\\w+):\\s+([\\w_/]+)\\s\\((\\w+)\\)")
	for e : String in error_message.split("\n"):
		var parts : PackedStringArray = e.split(":", true, 3)
		if parts.size() < 4:
			continue
		var message : String = parts[3].strip_edges()
		if message == "" or message == "'' : compilation terminated":
			continue
		var line : int = parts[2].strip_edges().to_int()
		var node_name : String = ""
		var section : String = ""
		for l in range(mini(line-1, code_lines.size()-1), -1, -1):
			if code_lines[l].find("// #") != -1:
				var re_match : RegExMatch = regex.search(code_lines[l])
				if re_match:
					section = re_match.strings[1]
					node_name = re_match.strings[2]
				break
		var code_line : String = code_lines[line-1].strip_edges() if line >= 1 and line <= code_lines.size() else ""
		rv.append({ line=line, message=message, node=node_name, section=section, code=code_line })
	return rv


func run(h : Node, args : PackedStringArray) -> void:
	host = h
	var options : Dictionary = parse_inspect_args(args)
	for e : String in options.errors:
		host.show_error(e, EXIT_BAD_ARGS)
	var result : Dictionary = {}
	if host.exit_code == EXIT_OK:
		match options.mode:
			"--list-nodes":
				result = await list_nodes()
			"--describe-node":
				result = await describe_nodes(options.types, options.all)
			"--validate":
				result = await validate_files(options.files)
	if options.json:
		var summary : Dictionary = {
			mm_cli = 1,
			mode = options.mode.trim_prefix("--"),
			ok = (host.exit_code == EXIT_OK),
			exit_code = host.exit_code,
			warnings = Array(host.warnings),
			errors = Array(host.errors)
		}
		summary.merge(result)
		print(JSON.stringify(to_json_safe(summary)))
	else:
		print(JSON.stringify(to_json_safe(result), "\t"))
	host.get_tree().quit(host.exit_code)

# --list-nodes

func create_library_manager() -> Node:
	var manager : Node = load("res://material_maker/tools/library_manager/library_manager.gd").new()
	manager.name = "NodeLibraryManager"
	for k : String in LIBRARY_MANAGER_SETTINGS.keys():
		manager.set(k, LIBRARY_MANAGER_SETTINGS[k])
	manager.sections = LIBRARY_SECTIONS
	add_child(manager)
	return manager

# Short description of a generator or library item (falls back to the long description)
static func generator_shortdesc(data : Dictionary) -> String:
	var desc_source : Dictionary = data
	if data.has("shader_model") and data.shader_model is Dictionary:
		desc_source = data.shader_model
	for k : String in [ "shortdesc", "longdesc" ]:
		if desc_source.has(k) and desc_source[k] is String and desc_source[k] != "":
			return desc_source[k]
	return ""

func list_nodes() -> Dictionary:
	var manager : Node = create_library_manager()
	await manager.libraries_changed
	var items : Array[Dictionary] = []
	var categories : Dictionary = {}
	for li in manager.get_child_count():
		var library : Node = manager.get_child(li)
		var library_enabled : bool = manager.disabled_libraries.find(library.library_path) == -1
		for i : Dictionary in library.library_items:
			var tree_item : String = i.tree_item
			var category : String = tree_item.get_slice("/", 0)
			var type : String = i.type if i.has("type") else ""
			var inline_graph : bool = i.has("nodes") or i.has("shader_model")
			var shortdesc : String = generator_shortdesc(i)
			if shortdesc == "" and not inline_graph and mm_loader.predefined_generators.has(type):
				shortdesc = generator_shortdesc(mm_loader.predefined_generators[type])
			var aliases : String = manager.get_aliases(tree_item)
			items.append({
				tree_item = tree_item,
				display_name = i.display_name,
				category = category,
				type = type,
				library = library.library_name,
				enabled = library_enabled and manager.is_section_enabled(category),
				inline_graph = inline_graph,
				shortdesc = shortdesc,
				keywords = Array(aliases.split(",", false)) if aliases != "" else []
			})
			if type != "" and not inline_graph and not categories.has(type):
				categories[type] = category
	var type_names : Array = mm_loader.predefined_generators.keys()
	for t : String in BUILTIN_TYPES:
		if not type_names.has(t):
			type_names.append(t)
	type_names.sort()
	var types : Array[Dictionary] = []
	for t : String in type_names:
		var data : Dictionary = mm_loader.predefined_generators.get(t, {})
		var label : String = ""
		if data.has("shader_model") and data.shader_model is Dictionary and data.shader_model.has("name"):
			label = data.shader_model.name
		elif data.has("label"):
			label = data.label
		types.append({
			type = t,
			label = label,
			category = categories.get(t, ""),
			in_library = categories.has(t),
			builtin = BUILTIN_TYPES.has(t),
			shortdesc = generator_shortdesc(data)
		})
	manager.queue_free()
	return { items = items, types = types }

# --describe-node

func describe_type(type : String) -> Dictionary:
	if type.begins_with("website:"):
		return {}
	if not mm_loader.predefined_generators.has(type) and not BUILTIN_TYPES.has(type):
		return {}
	var gen : MMGenBase = await mm_loader.create_gen(BUILTIN_DATA[type].duplicate(true) if BUILTIN_DATA.has(type) else { type=type })
	if gen == null:
		return {}
	# Generators expect a graph as parent, and some only set up their parameters and ports in
	# _ready() (linked remote parameters, switch)
	var container : MMGenGraph = MMGenGraph.new()
	if not DESCRIBE_OUTSIDE_TREE.has(type):
		add_child(container)
	container.add_child(gen)
	var rv : Dictionary = {
		type = type,
		generator = gen.get_script().get_global_name(),
		label = gen.get_type_name(),
		description = gen.get_description(),
		parameters = parameter_defs_with_values(gen),
		inputs = gen.get_input_defs(),
		outputs = gen.get_output_defs()
	}
	var data : Dictionary = mm_loader.predefined_generators.get(type, {})
	if data.has("shader_model") and data.shader_model is Dictionary:
		for k : String in [ "shortdesc", "longdesc" ]:
			if data.shader_model.has(k):
				rv[k] = data.shader_model[k]
	else:
		for k : String in [ "shortdesc", "longdesc" ]:
			if data.has(k):
				rv[k] = data[k]
	if data.has("generic_size"):
		rv.generic_size = data.generic_size
	rv = to_json_safe(rv)
	if container.get_parent() == self:
		remove_child(container)
	container.free()
	return rv

# Parameter definitions, with "default" set to the value a new node actually starts with (for
# graphs, the def of a linked parameter carries the inner node's default, not the graph's value)
static func parameter_defs_with_values(gen : MMGenBase) -> Array:
	var rv : Array = []
	for d in gen.get_parameter_defs():
		var p : Dictionary = d.duplicate()
		if p.has("name") and gen.parameters.has(p.name) and gen.parameters[p.name] != null:
			if p.has("default") and JSON.stringify(to_json_safe(p.default)) != JSON.stringify(to_json_safe(gen.parameters[p.name])):
				p.def_default = p.default
			p.default = gen.parameters[p.name]
		rv.append(p)
	return rv

func describe_nodes(types : Array, all : bool) -> Dictionary:
	if all:
		types = mm_loader.predefined_generators.keys()
		for t : String in BUILTIN_TYPES:
			if not types.has(t):
				types.append(t)
		types.sort()
	var nodes : Array[Dictionary] = []
	for t : String in types:
		var d : Dictionary = await describe_type(t)
		if d.is_empty():
			host.show_error("unknown node type "+t, EXIT_LOAD)
		else:
			nodes.append(d)
	return { nodes = nodes }

# --validate

func validate_files(files : Array) -> Dictionary:
	var results : Array[Dictionary] = []
	for f : String in files:
		var r : Dictionary = await validate_file(f)
		results.append(r)
		for e : Dictionary in r.errors:
			host.errors.append("%s: %s" % [ f.get_file(), e.message ])
		for w : Dictionary in r.warnings:
			host.warnings.append("%s: %s" % [ f.get_file(), w.message ])
		if r.load_failed:
			host.exit_code = maxi(host.exit_code, EXIT_LOAD)
		elif not r.ok:
			host.exit_code = maxi(host.exit_code, EXIT_INVALID)
		r.erase("load_failed")
	return { files = results }

func validate_file(path : String) -> Dictionary:
	var rv : Dictionary = { input=path, ok=false, load_failed=true, nodes=0, outputs_checked=0, errors=[] as Array[Dictionary], warnings=[] as Array[Dictionary] }
	var file : FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		rv.errors.append(issue("unreadable_file", "/", "", "cannot read %s" % path))
		return rv
	var data : Dictionary = MMLoader.string_to_dict_tree(file.get_as_text())
	file = null
	if data.is_empty():
		rv.errors.append(issue("invalid_json", "/", "", "%s is not a valid material file" % path))
		return rv
	var gen : MMGenBase = await mm_loader.load_gen(path)
	if gen == null:
		rv.errors.append(issue("load_failed", "/", "", "cannot load %s" % path))
		return rv
	rv.load_failed = false
	add_child(gen)
	if gen is MMGenGraph:
		check_graph(gen, data, "/", rv)
	if rv.errors.is_empty():
		await check_shaders(gen, rv)
	else:
		# Broken nodes or connections make downstream shaders fail too: fix those first
		rv.warnings.append(issue("shader_check_skipped", "/", "", "shaders were not compiled because the graph has errors"))
	rv.ok = rv.errors.is_empty()
	remove_child(gen)
	gen.free()
	return rv

static func port_types(defs : Array) -> Array:
	var rv : Array = []
	for d in defs:
		rv.append(d.type if d is Dictionary and d.has("type") else "any")
	return rv

func check_graph(graph : MMGenGraph, data : Dictionary, graph_path : String, rv : Dictionary) -> void:
	var nodes : Array = data.nodes if data.has("nodes") and data.nodes is Array else []
	var missing : Array = []
	var port_defs : Dictionary = {}
	for n in nodes:
		if not n is Dictionary or not n.has("name"):
			continue
		var child : Node = graph.get_node_or_null(NodePath(str(n.name)))
		if child == null or not child is MMGenBase:
			missing.append(str(n.name))
			rv.errors.append(issue("unknown_type", graph_path, str(n.name), "node %s has unknown type %s" % [ n.name, n.get("type", "?") ]))
			continue
		rv.nodes += 1
		port_defs[str(n.name)] = { inputs=port_types(child.get_input_defs()), outputs=port_types(child.get_output_defs()) }
		if child is MMGenGraph and n.has("nodes"):
			check_graph(child, n, graph_path.path_join(str(n.name)), rv)
	var connections : Array = []
	if data.has("connections"):
		if data.connections is Array:
			connections = data.connections
		elif data.connections is Dictionary:
			connections = graph.connections_from_compact(data.connections)
	rv.errors.append_array(check_connections(connections, port_defs, missing, mm_io_types.types, graph_path))
	# Connections the graph refused (e.g. loops)
	for c in connections:
		if not c is Dictionary or not port_defs.has(str(c.get("from", ""))) or not port_defs.has(str(c.get("to", ""))):
			continue
		var found : bool = false
		for gc : Dictionary in graph.connections:
			if gc.from == str(c.from) and gc.to == str(c.to) and gc.from_port == int(c.from_port) and gc.to_port == int(c.to_port):
				found = true
				break
		if not found:
			var replaced : bool = false
			for gc : Dictionary in graph.connections:
				if gc.to == str(c.to) and gc.to_port == int(c.to_port):
					replaced = true
			if not replaced:
				rv.errors.append(issue("connection_rejected", graph_path, str(c.to), "connection %s:%s -> %s:%s was rejected by the engine (loop?)" % [ c.from, port_str(c.from_port), c.to, port_str(c.to_port) ]))

# Collects the generators whose outputs are compiled: every node of the graph and of its sub-graphs
static func shader_generators(gen : MMGenBase, graph_path : String, rv : Array[Dictionary]) -> void:
	for c in gen.get_children():
		if not c is MMGenBase:
			continue
		var path : String = graph_path.path_join(c.name)
		if c is MMGenGraph:
			shader_generators(c, path, rv)
		if NO_SHADER_TYPES.has(c.get_type()) or c is MMGenMaterial or c is MMGenIOs or c is MMGenRemote:
			continue
		rv.append({ gen=c, path=path })

func compile_output(gen : MMGenBase, output_index : int) -> Dictionary:
	var source : MMGenBase.ShaderCode = gen.get_shader_code("uv", output_index, MMGenContext.new())
	if source.output_type == "":
		return { skipped="no code" }
	if source.output_type == "f":
		source.output_type = "rgba"
	if not source.output_values.has("rgba"):
		if not mm_io_types.types.has(source.output_type) or not mm_io_types.types[source.output_type].has("preview"):
			return { skipped="no preview for type "+source.output_type }
		var preview_code : String = mm_io_types.types[source.output_type].preview
		preview_code = preview_code.replace("uniform", "const")
		preview_code = preview_code.replace("const sampler2D", "uniform sampler2D")
		preview_code = preview_code.replace("preview_size", "64")
		preview_code = preview_code.replace("$(code)", source.code)
		preview_code = preview_code.replace("$(value)", source.output_values[source.output_type])
		source.defs += preview_code
		source.code = ""
		source.output_values.rgba = "preview_2d(uv)"
		source.output_type = "rgba"
	var capture : ShaderErrorCapture = ShaderErrorCapture.new()
	var previous_handler = mm_renderer.shader_error_handler
	mm_renderer.shader_error_handler = capture
	var compute_shader : MMComputeShader = MMComputeShader.new()
	var status : bool = await compute_shader.set_shader_from_shadercode(source, false)
	mm_renderer.shader_error_handler = previous_handler
	if compute_shader.shader.is_valid():
		mm_renderer.rendering_device.free_rid(compute_shader.shader)
	var messages : Array[Dictionary] = []
	for c : Dictionary in capture.captured:
		messages.append_array(parse_shader_error(c.shader, c.error))
	capture.free()
	return { ok=status, messages=messages }

func check_shaders(gen : MMGenBase, rv : Dictionary) -> void:
	if mm_renderer.rendering_device == null:
		rv.warnings.append(issue("shader_check_skipped", "/", "", "no rendering device (headless?), shaders were not compiled"))
		return
	var generators : Array[Dictionary] = []
	shader_generators(gen, "/", generators)
	# The same faulty node shows up in every shader that uses it: report each error once
	var reported : Dictionary = {}
	for g : Dictionary in generators:
		var outputs : Array = g.gen.get_output_defs()
		for i in outputs.size():
			var result : Dictionary = await compile_output(g.gen, i)
			if result.has("skipped"):
				continue
			rv.outputs_checked += 1
			if result.ok:
				continue
			if result.messages.is_empty():
				result.messages.append({ line=0, message="shader compilation failed", node="", section="", code="" })
			# One error per faulty node, with all its messages; the node is the one named by the
			# generated code where the error is, which may be upstream of the compiled output
			var output : String = "%s:%d" % [ g.path, i ]
			for m : Dictionary in result.messages:
				var node_name : String = m.node if m.node != "" else g.gen.name
				var key : String = node_name+"|"+m.section
				if reported.has(key):
					var e : Dictionary = reported[key]
					if not e.outputs.has(output):
						e.outputs.append(output)
					if not e.messages.has(m.message):
						e.messages.append(m.message)
					continue
				var e : Dictionary = issue("shader_compile_error", g.path.get_base_dir(), node_name,
						"%s: %s (in the %s code, compiling output %s)" % [ node_name, m.message, m.section if m.section != "" else "generated", output ])
				e.section = m.section
				e.line = m.line
				e.code_line = m.code
				e.messages = [ m.message ]
				e.outputs = [ output ]
				reported[key] = e
				rv.errors.append(e)
