extends GutTest

const CliServe = preload("res://cli_serve.gd")

# Request parsing

func test_request_ok() -> void:
	var r: Dictionary = CliServe.parse_request({ id=3, method="load", params={ path="/a.ptex" } })
	assert_eq(r.error, "")
	assert_eq(r.id, 3)
	assert_eq(r.method, "load")
	assert_eq(r.params, { path="/a.ptex" })

func test_request_without_params() -> void:
	var r: Dictionary = CliServe.parse_request({ method="get_graph" })
	assert_eq(r.error, "")
	assert_eq(r.id, null)
	assert_eq(r.params, {})
	assert_eq(CliServe.parse_request({ method="get_graph", params=null }).params, {})

func test_request_errors() -> void:
	assert_ne(CliServe.parse_request([ 1, 2 ]).error, "")
	assert_ne(CliServe.parse_request({ id=1 }).error, "")
	assert_ne(CliServe.parse_request({ id=1, method=5 }).error, "")
	assert_ne(CliServe.parse_request({ id=1, method="" }).error, "")
	var r: Dictionary = CliServe.parse_request({ id=7, method="load", params=[ "x" ] })
	assert_ne(r.error, "")
	assert_eq(r.id, 7)

# Parameter coercion

func coerce(def: Dictionary, v: Variant) -> Dictionary:
	return CliServe.coerce_parameter(def, v)

func test_float() -> void:
	var def: Dictionary = { name="amount", type="float", min=0.0, max=1.0 }
	assert_eq(coerce(def, 1).value, 1.0)
	assert_true(coerce(def, 1).value is float)
	assert_eq(coerce(def, 0.25).value, 0.25)
	assert_eq(coerce(def, "0.5").value, 0.5)
	assert_eq(coerce(def, "$time*0.1").value, "$time*0.1")
	assert_ne(coerce(def, "x").error, "")
	assert_ne(coerce(def, true).error, "")
	assert_ne(coerce(def, null).error, "")

func test_enum() -> void:
	var def: Dictionary = { name="mode", type="enum", values=[ { name="Normal", value="normal" }, { name="Multiply", value="multiply" } ] }
	assert_eq(coerce(def, 1).value, 1)
	assert_eq(coerce(def, 1.0).value, 1)
	assert_eq(coerce(def, "multiply").value, 1)
	assert_eq(coerce(def, "Normal").value, 0)
	assert_ne(coerce(def, 2).error, "")
	assert_ne(coerce(def, 0.5).error, "")
	assert_ne(coerce(def, "screen").error, "")

func test_size_and_boolean() -> void:
	var size: Dictionary = { name="size", type="size", first=4, last=12 }
	assert_eq(coerce(size, 10).value, 10)
	assert_ne(coerce(size, 13).error, "")
	assert_ne(coerce(size, 3).error, "")
	var b: Dictionary = { name="flag", type="boolean" }
	assert_eq(coerce(b, true).value, true)
	assert_eq(coerce(b, 0).value, false)
	assert_ne(coerce(b, "yes").error, "")

func test_color() -> void:
	var def: Dictionary = { name="color", type="color" }
	assert_eq(coerce(def, { r=1, g=0.5, b=0, a=1 }).value, Color(1, 0.5, 0, 1))
	assert_eq(coerce(def, { r=1, g=0.5, b=0 }).value, Color(1, 0.5, 0, 1))
	assert_eq(coerce(def, [ 0, 0, 1 ]).value, Color(0, 0, 1, 1))
	assert_eq(coerce(def, "#ff0000").value, Color(1, 0, 0, 1))
	assert_ne(coerce(def, "red-ish").error, "")
	assert_ne(coerce(def, 3).error, "")

func test_objects() -> void:
	var def: Dictionary = { name="gradient", type="gradient" }
	var g: Dictionary = coerce(def, { type="Gradient", interpolation=1, points=[ { pos=0, r=0, g=0, b=0, a=1 }, { pos=1, r=1, g=1, b=1, a=1 } ] })
	assert_eq(g.error, "")
	assert_true(g.value is MMGradient)
	assert_ne(coerce(def, { points=[] }).error, "")
	assert_ne(coerce(def, 1).error, "")

func test_other_types_pass_through() -> void:
	assert_eq(coerce({ name="text", type="string" }, "abc").value, "abc")
