extends Node

# Command line export exit codes
const EXIT_OK : int = 0
const EXIT_BAD_ARGS : int = 1
const EXIT_LOAD : int = 2
const EXIT_EXPORT : int = 3

const DEFAULT_TARGET : String = "Godot/Godot 4 Standard"

var exit_code : int = EXIT_OK
var errors : PackedStringArray = PackedStringArray()
var warnings : PackedStringArray = PackedStringArray()

func show_error(message : String, code : int = EXIT_BAD_ARGS) -> void:
	printerr("ERROR: "+message)
	errors.append(message)
	exit_code = maxi(exit_code, code)

func show_warning(message : String) -> void:
	printerr("WARNING: "+message)
	warnings.append(message)

static func name_to_lower(s : String) -> String:
	s = s.strip_edges()
	s = s.to_lower()
	s = s.replace(" ", "_")
	s = s.remove_chars("()/\"")
	return s

# Parses the arguments that follow --export / --export-material (anything before is ignored).
# Returns the export options and a list of errors (that all map to EXIT_BAD_ARGS).
static func parse_export_args(args : PackedStringArray) -> Dictionary:
	var rv : Dictionary = {
		target = DEFAULT_TARGET,
		output_dir = "",
		output_file = "%f",
		size = 0,
		files = [] as Array[String],
		json = false,
		strict_target = false,
		errors = [] as Array[String]
	}
	var start : int = maxi(args.find("--export-material"), args.find("--export"))
	var i : int = start+1
	while i < args.size():
		var arg : String = args[i]
		match arg:
			"-t", "--target", "-o", "--output-dir", "--output-file", "--size":
				if i+1 >= args.size():
					rv.errors.append("missing value for "+arg)
					break
				i += 1
				var value : String = args[i]
				match arg:
					"-t", "--target":
						rv.target = value
					"-o", "--output-dir":
						rv.output_dir = value
					"--output-file":
						rv.output_file = value
					"--size":
						if not value.is_valid_int() or value.to_int() < 0:
							rv.errors.append("incorrect size "+value+" (expected an integer >= 0, 0 = the graph's size)")
						else:
							rv.size = value.to_int()
			"--json":
				rv.json = true
			"--strict-target":
				rv.strict_target = true
			"--export", "--export-material", "--no-splash":
				pass
			_:
				if arg.begins_with("-"):
					rv.errors.append("unknown option "+arg)
				else:
					rv.files.push_back(arg)
		i += 1
	if rv.files.is_empty() and rv.errors.is_empty():
		rv.errors.append("no input file")
	return rv

# Picks the export profile for a requested target. When there is no exact match, the
# most similar profile is used (with a warning), unless strict is set.
static func resolve_target(requested : String, profiles : Array, strict : bool) -> Dictionary:
	if profiles.find(requested) != -1:
		return { target=requested, warning="", error="" }
	var available : String = ", ".join(PackedStringArray(profiles))
	if strict:
		return { target="", warning="", error="unknown target \"%s\" (available: %s)" % [requested, available] }
	var best_target : String = ""
	var best_similarity : float = 0.0
	for p : String in profiles:
		var similarity : float = p.similarity(requested)
		if similarity > best_similarity:
			best_similarity = similarity
			best_target = p
	if best_target == "":
		return { target="", warning="", error="unknown target \"%s\" (available: %s)" % [requested, available] }
	return { target=best_target, warning="target \"%s\" not found, using \"%s\"" % [requested, best_target], error="" }

# Modification times of the files in a directory (used to find what an export wrote)
static func dir_snapshot(path : String) -> Dictionary:
	var rv : Dictionary = {}
	for f : String in DirAccess.get_files_at(path):
		rv[f] = FileAccess.get_modified_time(path.path_join(f))
	return rv

# Files named name_prefix* that are new or changed since the snapshot (other files may
# be written concurrently, e.g. a log the caller redirects into the output directory)
static func written_files(path : String, before : Dictionary, name_prefix : String) -> Array[String]:
	var rv : Array[String] = []
	var after : Dictionary = dir_snapshot(path)
	for f : String in after.keys():
		if f.begins_with(name_prefix) and (not before.has(f) or before[f] != after[f]):
			rv.append(path.path_join(f))
	rv.sort()
	return rv

func export_files(files, output_dir, target, target_file, image_size, strict_target : bool = false) -> Array[Dictionary]:
	var results : Array[Dictionary] = []
	var website_materials : Array = []
	var export_list : PackedStringArray = PackedStringArray()
	for f : String in files:
		var result : Dictionary = { input=f, target="", size=0, files=[] as Array[String], ok=false }
		results.append(result)
		var basename : String = f.get_file().get_basename()
		var mat_name : String = f.get_file().get_basename()
		var mat_author : String = "unknown"
		var gen = await mm_loader.load_gen(f)
		var from_website : bool = false
		if gen == null and f.begins_with("website:"):
			var asset_index = f.right(-8).to_int()
			basename = "website_"+str(asset_index)
			var http_request : HTTPRequest = HTTPRequest.new()
			add_child(http_request)
			var error : Error
			var data : String
			var json : JSON
			if website_materials.is_empty():
				error = http_request.request(MMPaths.WEBSITE_ADDRESS+"/api/getMaterials")
				if error == OK:
					data = ( await http_request.request_completed )[3].get_string_from_utf8()
					json = JSON.new()
					if json.parse(data) == OK and json.get_data() is Array:
						website_materials = json.get_data()
			for m in website_materials:
				if int(m.id) == asset_index:
					mat_name = m.name
					mat_author = m.author
					break
			error = http_request.request(MMPaths.WEBSITE_ADDRESS+"/api/getMaterial?id="+str(asset_index))
			if error != OK:
				show_error("Failed to download asset "+str(asset_index), EXIT_LOAD)
				continue
			data = ( await http_request.request_completed )[3].get_string_from_utf8()
			json = JSON.new()
			if json.parse(data) != OK or ! json.data is Dictionary:
				show_error("Failed to download asset "+str(asset_index), EXIT_LOAD)
				continue
			var parse_result : Dictionary = json.data
			if json.parse(parse_result.json) == OK and json.data is Dictionary:
				gen = await mm_loader.create_gen(json.data)
			else:
				show_error("Failed to download asset "+str(asset_index), EXIT_LOAD)
				continue
			from_website = true
		if gen == null:
			if FileAccess.file_exists(f):
				show_error("Cannot load %s (not a valid material file)" % f, EXIT_LOAD)
			else:
				show_error("Cannot load %s (no such file)" % f, EXIT_LOAD)
			continue
		var mat_name_lower = name_to_lower(mat_name)
		var mat_author_lower = name_to_lower(mat_author)
		var has_material : bool = false
		var failed : bool = false
		add_child(gen)
		var gen_stack : Array[MMGenBase] = [gen]
		while gen_stack.size():
			var c : MMGenBase = gen_stack.pop_back()
			gen_stack.append_array(c.get_children())
			if c.has_method("export_material"):
				var best_target : String = target
				if c.has_method("get_export_profiles"):
					has_material = true
					var resolved : Dictionary = resolve_target(target, c.get_export_profiles(), strict_target)
					if resolved.error != "":
						show_error(resolved.error, EXIT_BAD_ARGS)
						failed = true
						continue
					if resolved.warning != "":
						show_warning(resolved.warning)
					best_target = resolved.target
					result.target = best_target
					result.size = image_size if image_size > 0 else c.get_image_size()
				var target_file_name : String = target_file
				target_file_name = target_file_name.replace("%f", basename)
				target_file_name = target_file_name.replace("%N", mat_name)
				target_file_name = target_file_name.replace("%A", mat_author)
				target_file_name = target_file_name.replace("%n", mat_name_lower)
				target_file_name = target_file_name.replace("%a", mat_author_lower)
				var prefix : String = output_dir.path_join(target_file_name)
				var name_prefix : String = prefix.get_file()
				if c.has_method("get_export_profiles"):
					print("Exporting Material %s to %s..." % [f.get_file(), prefix])
				else:
					var file_name : String = c.interpret_file_name(c.parameters.suffix, prefix.get_base_dir())
					print("Saving additional export %s" % file_name)
					name_prefix = file_name.get_file()
				var before : Dictionary = dir_snapshot(prefix.get_base_dir())
				await c.export_material(prefix, best_target, image_size, true)
				var written : Array[String] = written_files(prefix.get_base_dir(), before, name_prefix)
				if written.is_empty():
					show_error("Export of %s wrote no files to %s" % [f.get_file(), prefix.get_base_dir()], EXIT_EXPORT)
					failed = true
				result.files.append_array(written)
				if from_website:
					export_list.append("\""+prefix.get_file()+"\": \""+mat_name+","+mat_author+"\"")
		if not has_material:
			show_error("No Material node in %s" % f, EXIT_LOAD)
			failed = true
		result.ok = not failed
		print("Done")
		gen.queue_free()
	if not export_list.is_empty():
		print(",\n".join(export_list))
	return results

func expand_files(files : Array[String]) -> Array[String]:
	var expanded_files : Array[String] = []
	for f : String in files:
		var basedir : String = f.get_base_dir()
		if basedir == "":
			basedir = "."
		var basename : String = f.get_file()
		if basename.find("*") != -1:
			var count : int = expanded_files.size()
			basename = basename.replace("*", ".*")
			var dir : DirAccess = DirAccess.open(basedir)
			if dir != null:
				var regex : RegEx = RegEx.new()
				regex.compile("^"+basename+"$")
				dir.list_dir_begin() # TODOGODOT4 fill missing arguments https://github.com/godotengine/godot/pull/40547
				var file_name = dir.get_next()
				while file_name != "":
					if regex.search(file_name) and file_name.get_extension() == "ptex":
						expanded_files.push_back(basedir+"/"+file_name)
					file_name = dir.get_next()
			if expanded_files.size() == count:
				show_error("No file matches "+f, EXIT_LOAD)
		elif f.begins_with("website:"):
			for m : String in f.right(-8).split(","):
				var index_range : PackedStringArray = m.split("-")
				match index_range.size():
					1:
						if m.is_valid_int():
							expanded_files.push_back("website:"+m)
					2:
						if index_range[0].is_valid_int() and index_range[1].is_valid_int():
							for mi in range(index_range[0].to_int(), index_range[1].to_int()+1):
								expanded_files.push_back("website:"+str(mi))
		else:
			expanded_files.push_back(f)
	return expanded_files

func finish(options : Dictionary, results : Array[Dictionary]) -> void:
	if options.get("json", false):
		var all_files : Array[String] = []
		for r : Dictionary in results:
			all_files.append_array(r.files)
		var summary : Dictionary = {
			mm_cli = 1,
			ok = (exit_code == EXIT_OK),
			exit_code = exit_code,
			target_requested = options.get("target", ""),
			size_requested = options.get("size", 0),
			output_dir = options.get("output_dir", ""),
			materials = results,
			files = all_files,
			warnings = Array(warnings),
			errors = Array(errors)
		}
		print(JSON.stringify(summary))
	get_tree().quit(exit_code)

func _ready():
	RenderingServer.set_default_clear_color(Color.BLACK)
	var args : PackedStringArray = OS.get_cmdline_args()
	if ("--export" in args) or ("--export-material" in args):
		print("Exporting...")
		var options : Dictionary = parse_export_args(args)
		for e : String in options.errors:
			show_error(e, EXIT_BAD_ARGS)
		if exit_code != EXIT_OK:
			finish(options, [])
			return
		var dir : DirAccess = DirAccess.open(".")
		print("Current dir: ", dir.get_current_dir())
		if options.output_dir == "":
			options.output_dir = dir.get_current_dir()
		print("Output dir: ", options.output_dir)
		if ! DirAccess.dir_exists_absolute(options.output_dir):
			if DirAccess.make_dir_recursive_absolute(options.output_dir) != OK:
				show_error("Cannot create output directory "+options.output_dir, EXIT_EXPORT)
				finish(options, [])
				return
		var expanded_files : Array[String] = expand_files(options.files)
		var results : Array[Dictionary] = await export_files(expanded_files, options.output_dir, options.target, options.output_file, options.size, options.strict_target)
		finish(options, results)
	else:
		var no_logo : bool = ( args.find("--no-splash") != -1 )
		var scene : PackedScene
		if no_logo:
			scene = load("res://material_maker/main_window.tscn")
		else:
			scene = load("res://splash_screen/splash_screen.tscn")
		await get_tree().process_frame
		get_tree().change_scene_to_packed(scene)
