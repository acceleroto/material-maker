extends GutTest

const ParseArgs = preload("res://parse_args.gd")

const PROFILES: Array = ["Godot/Godot 4 Standard", "Unity/3D", "Unity/HDRP", "Unity/URP"]

func parse(args: Array) -> Dictionary:
	return ParseArgs.parse_export_args(PackedStringArray(args))

func test_defaults() -> void:
	var o: Dictionary = parse(["--export-material", "/a/b.ptex"])
	assert_eq(o.errors, [])
	assert_eq(o.target, ParseArgs.DEFAULT_TARGET)
	assert_eq(o.size, 0)
	assert_eq(o.output_dir, "")
	assert_eq(o.output_file, "%f")
	assert_eq(o.files, ["/a/b.ptex"])
	assert_false(o.json)
	assert_false(o.strict_target)

func test_all_options() -> void:
	var o: Dictionary = parse(["--export-material", "--target", "Unity/URP", "-o", "/out", "--output-file", "%n",
			"--size", "1024", "--json", "--strict-target", "/a.ptex", "/b.ptex"])
	assert_eq(o.errors, [])
	assert_eq(o.target, "Unity/URP")
	assert_eq(o.output_dir, "/out")
	assert_eq(o.output_file, "%n")
	assert_eq(o.size, 1024)
	assert_true(o.json)
	assert_true(o.strict_target)
	assert_eq(o.files, ["/a.ptex", "/b.ptex"])

func test_short_options() -> void:
	var o: Dictionary = parse(["--export", "-t", "Unity/3D", "--output-dir", "/out", "/a.ptex"])
	assert_eq(o.errors, [])
	assert_eq(o.target, "Unity/3D")
	assert_eq(o.output_dir, "/out")

func test_args_before_export_flag_are_ignored() -> void:
	var o: Dictionary = parse(["-s", "res://something.gd", "--export-material", "/a.ptex"])
	assert_eq(o.errors, [])
	assert_eq(o.files, ["/a.ptex"])

func test_size_zero_means_graph_size() -> void:
	var o: Dictionary = parse(["--export-material", "--size", "0", "/a.ptex"])
	assert_eq(o.errors, [])
	assert_eq(o.size, 0)

func test_bad_sizes() -> void:
	for s in ["-1", "abc", "12.5", ""]:
		var o: Dictionary = parse(["--export-material", "--size", s, "/a.ptex"])
		assert_eq(o.errors.size(), 1, "size '%s' should be rejected" % s)

func test_missing_values() -> void:
	for opt in ["--target", "-t", "-o", "--output-dir", "--output-file", "--size"]:
		var o: Dictionary = parse(["--export-material", "/a.ptex", opt])
		assert_eq(o.errors, ["missing value for " + opt])

func test_unknown_option() -> void:
	var o: Dictionary = parse(["--export-material", "--frobnicate", "/a.ptex"])
	assert_eq(o.errors, ["unknown option --frobnicate"])

func test_no_input_file() -> void:
	var o: Dictionary = parse(["--export-material", "--target", "Unity/URP"])
	assert_eq(o.errors, ["no input file"])

func test_resolve_exact_target() -> void:
	var r: Dictionary = ParseArgs.resolve_target("Unity/URP", PROFILES, false)
	assert_eq(r, { target="Unity/URP", warning="", error="" })
	r = ParseArgs.resolve_target("Unity/URP", PROFILES, true)
	assert_eq(r, { target="Unity/URP", warning="", error="" })

func test_resolve_similar_target_warns() -> void:
	var r: Dictionary = ParseArgs.resolve_target("Unity/URPx", PROFILES, false)
	assert_eq(r.target, "Unity/URP")
	assert_string_contains(r.warning, "not found")
	assert_eq(r.error, "")

func test_resolve_strict_target_fails() -> void:
	var r: Dictionary = ParseArgs.resolve_target("Unity/URPx", PROFILES, true)
	assert_eq(r.target, "")
	assert_string_contains(r.error, "unknown target")
	assert_string_contains(r.error, "Unity/URP")

func test_resolve_no_similar_target_fails() -> void:
	var r: Dictionary = ParseArgs.resolve_target("Unity/URP", ["Blender"], false)
	assert_eq(r.target, "")
	assert_string_contains(r.error, "unknown target")
