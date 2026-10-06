extends GutTest

const CliInspect = preload("res://cli_inspect.gd")

func parse(args: Array) -> Dictionary:
	return CliInspect.parse_inspect_args(PackedStringArray(args))

# Argument parsing

func test_list_nodes() -> void:
	var o: Dictionary = parse(["--list-nodes", "--json"])
	assert_eq(o.errors, [])
	assert_eq(o.mode, "--list-nodes")
	assert_true(o.json)

func test_describe_types() -> void:
	var o: Dictionary = parse(["--describe-node", "bricks3", "blend2"])
	assert_eq(o.errors, [])
	assert_eq(o.types, ["bricks3", "blend2"])
	assert_false(o.all)
	assert_false(o.json)

func test_describe_all() -> void:
	var o: Dictionary = parse(["--path", "/repo", "--describe-node", "--all", "--json"])
	assert_eq(o.errors, [])
	assert_true(o.all)

func test_describe_needs_type() -> void:
	assert_eq(parse(["--describe-node", "--json"]).errors.size(), 1)
	assert_eq(parse(["--describe-node", "--all", "bricks3"]).errors.size(), 1)

func test_validate_files() -> void:
	var o: Dictionary = parse(["--validate", "/a.ptex", "/b.ptex", "--json"])
	assert_eq(o.errors, [])
	assert_eq(o.files, ["/a.ptex", "/b.ptex"])

func test_validate_needs_file() -> void:
	assert_eq(parse(["--validate"]).errors, ["no input file"])

func test_modes_cannot_be_combined() -> void:
	assert_eq(parse(["--validate", "/a.ptex", "--list-nodes"]).errors.size(), 1)

func test_unknown_option_and_stray_argument() -> void:
	assert_eq(parse(["--list-nodes", "--bogus"]).errors, ["unknown option --bogus"])
	assert_eq(parse(["--list-nodes", "stray"]).errors, ["unexpected argument stray"])
	assert_eq(parse(["--list-nodes", "--all"]).errors.size(), 1)

func test_render_output() -> void:
	var o: Dictionary = parse(["--render-output", "/a.ptex", "--node", "graph/Bricks", "--port", "1", "--size", "256", "-o", "/out/b.png", "--json"])
	assert_eq(o.errors, [])
	assert_eq(o.mode, "--render-output")
	assert_eq(o.files, ["/a.ptex"])
	assert_eq(o.node, "graph/Bricks")
	assert_eq(o.port, 1)
	assert_eq(o.size, 256)
	assert_eq(o.output, "/out/b.png")

func test_render_output_defaults() -> void:
	var o: Dictionary = parse(["--render-output", "/a.ptex", "--node", "Perlin", "--output", "/b.exr"])
	assert_eq(o.errors, [])
	assert_eq(o.port, 0)
	assert_eq(o.size, CliInspect.RENDER_DEFAULT_SIZE)

func test_render_output_errors() -> void:
	assert_eq(parse(["--render-output", "/a.ptex", "-o", "/b.png"]).errors, ["no node (expected --node <name>)"])
	assert_eq(parse(["--render-output", "/a.ptex", "--node", "n"]).errors, ["no output file (expected -o <file.png>)"])
	assert_eq(parse(["--render-output", "--node", "n", "-o", "/b.png"]).errors.size(), 1)
	assert_eq(parse(["--render-output", "/a.ptex", "/c.ptex", "--node", "n", "-o", "/b.png"]).errors.size(), 1)
	assert_eq(parse(["--render-output", "/a.ptex", "--node", "n", "-o", "/b.txt"]).errors.size(), 1)
	assert_eq(parse(["--render-output", "/a.ptex", "--node", "n", "--port", "-1", "-o", "/b.png"]).errors.size(), 1)
	assert_eq(parse(["--render-output", "/a.ptex", "--node", "n", "--size", "8", "-o", "/b.png"]).errors.size(), 1)
	assert_eq(parse(["--render-output", "/a.ptex", "--node"]).errors, ["--node needs a value"])

func test_render_options_need_render_mode() -> void:
	assert_eq(parse(["--validate", "/a.ptex", "--node", "n"]).errors, ["--node is only valid with --render-output"])

# JSON conversion

func test_to_json_safe() -> void:
	var v: Variant = CliInspect.to_json_safe({ c=Color(1, 0.5, 0, 1), v=Vector2(1, 2), n=&"x", f=2.0, g=0.25, a=[Vector3(1, 2, 3)] })
	assert_eq(v.c, { r=1, g=0.5, b=0, a=1 })
	assert_eq(v.v, { x=1, y=2 })
	assert_eq(v.n, "x")
	assert_typeof(v.f, TYPE_INT)
	assert_eq(v.g, 0.25)
	assert_eq(v.a, [{ x=1, y=2, z=3 }])

# Connection checks

const IO_TYPES: Dictionary = {
	f = { slot_type = 0 }, rgb = { slot_type = 0 }, rgba = { slot_type = 0 },
	sdf2d = { slot_type = 1 }, fill = { slot_type = 5 }
}
const PORTS: Dictionary = {
	bricks = { inputs = ["f"], outputs = ["f", "fill"] },
	blend = { inputs = ["rgba", "rgba", "f"], outputs = ["rgba"] },
	circle = { inputs = [], outputs = ["sdf2d"] }
}

func conn(from: String, from_port, to: String, to_port) -> Dictionary:
	return { from = from, from_port = from_port, to = to, to_port = to_port }

func codes(issues: Array) -> Array:
	var rv: Array = []
	for i: Dictionary in issues:
		rv.append(i.code)
	return rv

func test_good_connections() -> void:
	var issues: Array = CliInspect.check_connections([conn("bricks", 0, "blend", 2), conn("blend", 0, "bricks", 0)], PORTS, [], IO_TYPES, "/")
	assert_eq(issues, [])

func test_bad_ports() -> void:
	var issues: Array = CliInspect.check_connections([conn("bricks", 5, "blend", 0), conn("bricks", 0, "blend", 3)], PORTS, [], IO_TYPES, "/")
	assert_eq(codes(issues), ["bad_output_port", "bad_input_port"])
	assert_eq(issues[0].node, "bricks")

func test_unknown_and_missing_nodes() -> void:
	var issues: Array = CliInspect.check_connections([conn("nope", 0, "blend", 0), conn("broken", 0, "blend", 1)], PORTS, ["broken"], IO_TYPES, "/g")
	assert_eq(codes(issues), ["unknown_node"])
	assert_eq(issues[0].graph_path, "/g")

func test_type_mismatch() -> void:
	var issues: Array = CliInspect.check_connections([conn("bricks", 1, "blend", 0), conn("circle", 0, "bricks", 0)], PORTS, [], IO_TYPES, "/")
	assert_eq(codes(issues), ["port_type_mismatch", "port_type_mismatch"])

func test_input_multiply_connected() -> void:
	var issues: Array = CliInspect.check_connections([conn("bricks", 0, "blend", 2), conn("blend", 0, "blend", 2)], PORTS, [], IO_TYPES, "/")
	assert_eq(codes(issues), ["input_multiply_connected"])

func test_malformed_connection() -> void:
	var issues: Array = CliInspect.check_connections([{ from = "bricks" }, conn("bricks", -1, "blend", 0), conn("bricks", 0.5, "blend", 0)], PORTS, [], IO_TYPES, "/")
	assert_eq(codes(issues), ["bad_connection", "bad_output_port", "bad_output_port"])

func test_real_io_types_compatibility() -> void:
	assert_true(CliInspect.is_compatible_port_type("f", "rgba", mm_io_types.types))
	assert_true(CliInspect.is_compatible_port_type("sdf3d", "sdf3dc", mm_io_types.types))
	assert_false(CliInspect.is_compatible_port_type("fill", "rgba", mm_io_types.types))
	assert_false(CliInspect.is_compatible_port_type("sdf2d", "f", mm_io_types.types))

# Shader error parsing

func test_parse_shader_error() -> void:
	var shader: String = "void a() {}\n// #code: blend_2 (n12)\nfloat x = foo;\n"
	var errors: Array = CliInspect.parse_shader_error(shader, "error\nERROR: 0:3: 'foo' : undeclared identifier\nERROR: 0:3: '' : compilation terminated")
	assert_eq(errors.size(), 1)
	assert_eq(errors[0].node, "blend_2")
	assert_eq(errors[0].section, "code")
	assert_eq(errors[0].line, 3)
	assert_eq(errors[0].code, "float x = foo;")
	assert_string_contains(errors[0].message, "undeclared identifier")

# Library manager settings must match the editor's add-node menu

func test_library_manager_settings_match_main_window() -> void:
	var state: SceneState = load("res://material_maker/main_window.tscn").get_state()
	var found: bool = false
	for n in state.get_node_count():
		if state.get_node_name(n) != "NodeLibraryManager":
			continue
		found = true
		for p in state.get_node_property_count(n):
			var prop: String = state.get_node_property_name(n, p)
			if CliInspect.LIBRARY_MANAGER_SETTINGS.has(prop):
				assert_eq(CliInspect.LIBRARY_MANAGER_SETTINGS[prop], state.get_node_property_value(n, p), prop)
			elif prop == "sections":
				assert_eq(CliInspect.LIBRARY_SECTIONS, state.get_node_property_value(n, p))
	assert_true(found)

# Describing instantiated generators

func describe(type: String) -> Dictionary:
	var inspect: Node = CliInspect.new()
	add_child_autofree(inspect)
	return await inspect.describe_type(type)

func test_describe_bricks3() -> void:
	var d: Dictionary = await describe("bricks3")
	assert_eq(d.generator, "MMGenShader")
	assert_eq(d.label, "Bricks")
	var names: Array = d.parameters.map(func(p): return p.name)
	assert_true(names.has("mortar"))
	assert_eq(d.inputs.map(func(p): return p.type), ["f", "f", "f"])
	assert_eq(d.outputs.map(func(p): return p.type), ["f", "fill", "fill"])

# (buffer is not tested here: its _ready() compiles a shader, which fails with --headless)
func test_describe_switch_and_unknown() -> void:
	var d: Dictionary = await describe("switch")
	assert_eq(d.generator, "MMGenSwitch")
	assert_eq(d.inputs.size(), 4)
	assert_eq(d.outputs.size(), 2)
	assert_eq(await describe("no_such_type"), {})

func test_describe_graph_has_linked_parameters() -> void:
	var d: Dictionary = await describe("convert_to_rgb")
	assert_eq(d.generator, "MMGenGraph")
	assert_eq(d.parameters[0].type, "enum")
