extends Node

# --render-preview: lit 3D preview of a material, rendered with the editor's own 3D preview scene
# (material_maker/panels/preview_3d), environments (EnvironmentManager) and the Material node's
# preview shader, from a fixed camera so that renders of different iterations are comparable.

const PREVIEW_SCENE : String = "res://material_maker/panels/preview_3d/preview_3d_scene.tscn"
const ENVIRONMENT_MANAGER_SCENE : String = "res://material_maker/tools/environment_manager/environment_manager.tscn"

# --mesh name -> object in preview_objects.tscn, its UV scale there (preview_mesh.gd replaces it
# with the user's own setting from mm_config.ini; renders must not depend on that), and the camera
# field of view: the editor's camera position and angle, but zoomed so the object fills the view
const MESHES : Dictionary = {
	sphere = { object="Sphere", uv_scale=Vector2(4, 2), fov=30.0 },
	plane = { object="Plane", uv_scale=Vector2(2, 2), fov=37.0 },
	cube = { object="Cube", uv_scale=Vector2(3, 2), fov=31.0 }
}

# Tesselation of the generated meshes (cube, plane); the editor's default
const TESSELATION_DETAIL : int = 256

# preview_mesh_generated.gd reads the tesselation detail from the main window, which does not
# exist in command line mode
class MainWindowStub:
	extends Node
	var preview_tesselation_detail : int = TESSELATION_DETAIL


var inspect : Node = null  # cli_inspect.gd: shared waits and exit codes
var host : Node = null     # parse_args.gd: errors and exit code


func render(inspector : Node, path : String, meshes : Array[String], env_name : String, size : int, output : String) -> Dictionary:
	inspect = inspector
	host = inspector.host
	var start : int = Time.get_ticks_msec()
	var rv : Dictionary = { input=path, meshes=meshes, env=env_name, size=size, file="" }
	var env_manager : Node = load(ENVIRONMENT_MANAGER_SCENE).instantiate()
	# Not added to the tree: its _exit_tree() rewrites user://environments.json
	env_manager.base_dir = MMPaths.get_resource_dir()
	env_manager._ready()
	var env_index : int = find_environment(env_manager, env_name)
	if env_index == -1:
		var names : PackedStringArray = PackedStringArray()
		for e : Dictionary in env_manager.get_environment_list():
			names.append(e.name)
		host.show_error("unknown --env %s (available: %s)" % [ env_name, ", ".join(names) ], inspect.EXIT_BAD_ARGS)
		env_manager.free()
		return rv
	rv.env = env_manager.get_environment(env_index).name
	rv.env_index = env_index
	if not await inspect.wait_for_rendering_device():
		host.show_error("no rendering device (headless?), cannot render", inspect.EXIT_RENDER)
		env_manager.free()
		return rv
	var gen : MMGenBase = await mm_loader.load_gen(path)
	if gen == null:
		host.show_error("Cannot load %s (%s)" % [ path, "not a valid material file" if FileAccess.file_exists(path) else "no such file" ], inspect.EXIT_LOAD)
		env_manager.free()
		return rv
	add_child(gen)
	var material : Node = gen.get_node_or_null("Material")
	if not material is MMGenMaterial:
		host.show_error("No Material node in %s" % path, inspect.EXIT_BAD_ARGS)
	else:
		rv.image_size = material.get_image_size()
		# The Material node builds its preview shader and textures one frame after loading
		for i in 3:
			await get_tree().process_frame
		await inspect.wait_for_buffers()
		var image : Image = await render_meshes(material, meshes, env_manager, env_index, size)
		var dir : String = output.get_base_dir()
		if image == null:
			host.show_error("rendering %s failed" % path.get_file(), inspect.EXIT_RENDER)
		elif not DirAccess.dir_exists_absolute(dir) and DirAccess.make_dir_recursive_absolute(dir) != OK:
			host.show_error("cannot create directory "+dir, inspect.EXIT_RENDER)
		elif save_image(image, output) != OK:
			host.show_error("cannot write "+output, inspect.EXIT_RENDER)
		else:
			rv.file = output
			rv.width = image.get_width()
			rv.height = image.get_height()
	remove_child(gen)
	gen.free()
	env_manager.free()
	rv.seconds = (Time.get_ticks_msec()-start)/1000.0
	return rv

static func find_environment(env_manager : Node, env_name : String) -> int:
	var list : Array = env_manager.get_environment_list()
	if env_name.is_valid_int():
		var index : int = env_name.to_int()
		return index if index >= 0 and index < list.size() else -1
	for i in list.size():
		if list[i].name.to_lower() == env_name.to_lower():
			return i
	return -1

static func save_image(image : Image, file_name : String) -> Error:
	match file_name.get_extension().to_lower():
		"jpg":
			return image.save_jpg(file_name, 0.95)
		"webp":
			return image.save_webp(file_name)
		"exr":
			return image.save_exr(file_name)
	return image.save_png(file_name)

# Renders each mesh in its own view and puts the views side by side
func render_meshes(material : MMGenMaterial, meshes : Array[String], env_manager : Node, env_index : int, size : int) -> Image:
	var viewport : SubViewport = SubViewport.new()
	viewport.size = Vector2i(size, size)
	viewport.own_world_3d = true
	viewport.transparent_bg = false
	viewport.msaa_3d = Viewport.MSAA_4X
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	var scene : Node3D = load(PREVIEW_SCENE).instantiate()
	viewport.add_child(scene)
	add_child(viewport)
	var objects : Node3D = scene.get_node("ObjectsPivot/Objects")
	var environment : Environment = scene.get_node("WorldEnvironment").environment
	var sun : DirectionalLight3D = scene.get_node("Sun")
	var camera : Camera3D = scene.get_node("Camera3D")
	await env_manager.apply_environment(env_index, environment, sun)
	var result : Image = Image.create(size*meshes.size(), size, false, Image.FORMAT_RGBA8)
	for i in meshes.size():
		var object : MeshInstance3D = objects.get_node(MESHES[meshes[i]].object)
		for o in objects.get_children():
			o.visible = (o == object)
		object.uv_scale = MESHES[meshes[i]].uv_scale
		camera.fov = MESHES[meshes[i]].fov
		await update_mesh(object)
		# Same centering as preview_3d.gd select_object()
		var aabb : AABB = object.get_aabb()
		object.transform.origin = -(aabb.position+0.5*aabb.size)
		await material.update_material(object.get_material())
		for f in 3:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var image : Image = viewport.get_texture().get_image()
		if image == null:
			result = null
			break
		image.convert(Image.FORMAT_RGBA8)
		result.blit_rect(image, Rect2i(Vector2i.ZERO, image.get_size()), Vector2i(i*size, 0))
	remove_child(viewport)
	viewport.free()
	return result

func update_mesh(object : MeshInstance3D) -> void:
	if not object.has_method("update_mesh"):
		return
	var stub : Node = null
	if mm_globals.main_window == null:
		stub = MainWindowStub.new()
		mm_globals.main_window = stub
	await object.update_mesh()
	if stub != null:
		mm_globals.main_window = null
		stub.free()
