"""Portable material fallbacks shared by the local Hunyuan worker and tests."""

import numpy as np
import trimesh
from PIL import Image



def estimate_base_colour(images: list[Image.Image]) -> np.ndarray:
    """Estimate foreground albedo without letting white backgrounds/highlights win."""
    samples: list[np.ndarray] = []
    for image in images:
        thumbnail = image.convert("RGBA").copy()
        thumbnail.thumbnail((384, 384), Image.Resampling.LANCZOS)
        rgba = np.asarray(thumbnail, dtype=np.uint8)
        pixels = rgba[rgba[:, :, 3] > 180, :3]
        if not len(pixels):
            continue
        step = max(1, len(pixels) // 25000)
        samples.append(pixels[::step])
    if not samples:
        return np.array([180, 180, 180, 255], dtype=np.uint8)

    pixels = np.concatenate(samples, axis=0).astype(np.float32)
    luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    low, high = np.percentile(luminance, [2.0, 98.0])
    pixels = pixels[(luminance >= low) & (luminance <= high)]
    if not len(pixels):
        pixels = np.concatenate(samples, axis=0).astype(np.float32)

    maximum = np.maximum(pixels.max(axis=1), 1.0)
    saturation = (pixels.max(axis=1) - pixels.min(axis=1)) / maximum
    saturated = pixels[saturation > 0.18]
    # When a meaningful coloured region exists, do not let neutral white
    # highlights or a small leaked backdrop dominate the fallback material.
    working = saturated if len(saturated) >= max(64, int(len(pixels) * 0.12)) else pixels
    quantized = np.clip((working / 32).astype(np.int16), 0, 7)
    keys = quantized[:, 0] * 64 + quantized[:, 1] * 8 + quantized[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    dominant = int(values[np.argmax(counts)])
    centre = np.array([(dominant // 64) * 32 + 16, ((dominant // 8) % 8) * 32 + 16, (dominant % 8) * 32 + 16])
    distances = np.linalg.norm(working - centre[None, :], axis=1)
    cluster = working[distances <= 72]
    if len(cluster) < 32:
        cluster = working
    rgb = np.median(cluster, axis=0)
    return np.r_[np.clip(np.rint(rgb), 0, 255).astype(np.uint8), 255]

def apply_pbr_material(mesh, base_colour: np.ndarray):
    material = trimesh.visual.material.PBRMaterial(
        name="AI PBR material",
        baseColorFactor=base_colour,
        metallicFactor=0.0,
        roughnessFactor=0.34,
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2), dtype=np.float32),
        material=material,
    )
    return mesh


def apply_multiview_vertex_colours(mesh, images: list[Image.Image], base_colour: np.ndarray):
    """Project canonical multiview colour into portable GLB vertex colours.

    This deterministic fallback is used when Hunyuan Paint's native CUDA
    rasterizer is unavailable. It preserves observed colour without pasting a
    complete rectangular photograph onto the mesh.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    if not len(vertices):
        return apply_pbr_material(mesh, base_colour)
    bounds_min = vertices.min(axis=0)
    bounds_span = np.maximum(vertices.max(axis=0) - bounds_min, 1e-6)
    normalized = (vertices - bounds_min) / bounds_span
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    view_specs = [
        (np.array([0.0, 0.0, 1.0], dtype=np.float32), normalized[:, 0]),
        (np.array([-1.0, 0.0, 0.0], dtype=np.float32), normalized[:, 2]),
        (np.array([0.0, 0.0, -1.0], dtype=np.float32), 1.0 - normalized[:, 0]),
        (np.array([1.0, 0.0, 0.0], dtype=np.float32), 1.0 - normalized[:, 2]),
    ]
    accumulated = np.zeros((len(vertices), 3), dtype=np.float32)
    total_weight = np.zeros(len(vertices), dtype=np.float32)
    vertical = 1.0 - normalized[:, 1]

    for image, (camera_direction, horizontal) in zip(images[:4], view_specs):
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        alpha = rgba[:, :, 3] > 127
        ys, xs = np.where(alpha)
        if not len(xs):
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        sample_x = np.clip(np.rint(x0 + horizontal * max(1, x1 - x0)), x0, x1).astype(int)
        sample_y = np.clip(np.rint(y0 + vertical * max(1, y1 - y0)), y0, y1).astype(int)
        valid = alpha[sample_y, sample_x]
        facing = np.clip(normals @ camera_direction, 0.0, 1.0)
        weight = np.where(valid, 0.08 + facing * facing, 0.0).astype(np.float32)
        accumulated += rgba[sample_y, sample_x, :3].astype(np.float32) * weight[:, None]
        total_weight += weight

    fallback = np.asarray(base_colour[:3], dtype=np.float32)
    colours = np.repeat(fallback[None, :], len(vertices), axis=0)
    covered = total_weight > 1e-5
    colours[covered] = accumulated[covered] / total_weight[covered, None]
    rgba_colours = np.column_stack(
        [
            np.clip(np.rint(colours), 0, 255).astype(np.uint8),
            np.full(len(vertices), 255, dtype=np.uint8),
        ]
    )
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=rgba_colours)
    return mesh


def _bilinear_rgba(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorized bilinear sampling for projective texture baking."""
    height, width = image.shape[:2]
    x = np.clip(x, 0.0, width - 1.0)
    y = np.clip(y, 0.0, height - 1.0)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    wx = (x - x0).astype(np.float32)[:, None]
    wy = (y - y0).astype(np.float32)[:, None]
    top = image[y0, x0].astype(np.float32) * (1.0 - wx) + image[y0, x1].astype(np.float32) * wx
    bottom = image[y1, x0].astype(np.float32) * (1.0 - wx) + image[y1, x1].astype(np.float32) * wx
    return top * (1.0 - wy) + bottom * wy


def _rasterized_view_depth(
    vertices: np.ndarray,
    faces: np.ndarray,
    camera_direction: np.ndarray,
    horizontal_axis: int,
    flip_horizontal: bool,
    resolution: int = 320,
) -> np.ndarray:
    """Build an orthographic z-buffer in the same space used for colour projection.

    A normal check alone is insufficient: a rear wing can face the camera while
    still being hidden behind the front wing.  Sampling it from the photograph
    duplicates markings across unrelated surfaces.  This depth map lets the CPU
    baker colour only the foremost surface at each source-image coordinate.
    """
    resolution = max(64, int(resolution))
    horizontal = vertices[:, horizontal_axis]
    if flip_horizontal:
        horizontal = 1.0 - horizontal
    vertical = 1.0 - vertices[:, 1]
    screen = np.column_stack(
        (horizontal * (resolution - 1), vertical * (resolution - 1))
    ).astype(np.float32)
    depth = vertices @ np.asarray(camera_direction, dtype=np.float32)
    depth_map = np.full((resolution, resolution), -np.inf, dtype=np.float32)

    for face in faces:
        triangle = screen[face]
        x0 = max(0, int(np.floor(triangle[:, 0].min())))
        x1 = min(resolution - 1, int(np.ceil(triangle[:, 0].max())))
        y0 = max(0, int(np.floor(triangle[:, 1].min())))
        y1 = min(resolution - 1, int(np.ceil(triangle[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue
        grid_x, grid_y = np.meshgrid(
            np.arange(x0, x1 + 1, dtype=np.float32) + 0.5,
            np.arange(y0, y1 + 1, dtype=np.float32) + 0.5,
        )
        ax, ay = triangle[0]
        bx, by = triangle[1]
        cx, cy = triangle[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(float(denominator)) < 1e-8:
            continue
        wa = ((by - cy) * (grid_x - cx) + (cx - bx) * (grid_y - cy)) / denominator
        wb = ((cy - ay) * (grid_x - cx) + (ax - cx) * (grid_y - cy)) / denominator
        wc = 1.0 - wa - wb
        inside = (wa >= -1e-4) & (wb >= -1e-4) & (wc >= -1e-4)
        if not np.any(inside):
            continue
        interpolated = wa * depth[face[0]] + wb * depth[face[1]] + wc * depth[face[2]]
        region = depth_map[y0 : y1 + 1, x0 : x1 + 1]
        region[inside] = np.maximum(region[inside], interpolated[inside])
    return depth_map


def _visible_in_view(
    positions: np.ndarray,
    camera_direction: np.ndarray,
    horizontal_axis: int,
    flip_horizontal: bool,
    depth_map: np.ndarray,
) -> np.ndarray:
    """Return whether projected surface samples are foremost in the source view."""
    height, width = depth_map.shape
    horizontal = positions[:, horizontal_axis]
    if flip_horizontal:
        horizontal = 1.0 - horizontal
    sample_x = np.clip(np.rint(horizontal * (width - 1)), 0, width - 1).astype(np.int32)
    sample_y = np.clip(np.rint((1.0 - positions[:, 1]) * (height - 1)), 0, height - 1).astype(np.int32)
    front_depth = depth_map[sample_y, sample_x]
    point_depth = positions @ np.asarray(camera_direction, dtype=np.float32)
    tolerance = 3.0 / max(width, height)
    return np.isfinite(front_depth) & (point_depth >= front_depth - tolerance)


def _texture_subject_alpha(rgba: np.ndarray) -> np.ndarray:
    """Remove uniform backdrop and soft cast shadows from a geometry mask.

    Segmentation masks are intentionally permissive so they do not cut thin
    geometry.  Texture projection needs a stricter interpretation: otherwise
    a white sweep or its grey shadow becomes albedo on the model.  Strong
    colour/darkness differences seed the subject and a small expansion keeps
    highlights, emblems and thin attachments next to those reliable pixels.
    """
    from scipy import ndimage

    alpha = rgba[:, :, 3] > 127
    if not np.any(alpha):
        return alpha
    rgb = rgba[:, :, :3].astype(np.float32)
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    background = np.median(border, axis=0)
    border_distance = np.linalg.norm(border - background[None, :], axis=1)
    # Do not apply aggressive subtraction when the photograph does not have a
    # stable studio-like background.
    if float(np.percentile(border_distance, 90)) > 42.0:
        return alpha

    distance = np.linalg.norm(rgb - background[None, None, :], axis=2)
    maximum = np.maximum(rgb.max(axis=2), 1.0)
    saturation = (rgb.max(axis=2) - rgb.min(axis=2)) / maximum
    border_noise = float(np.percentile(border_distance, 98))
    colour_threshold = max(30.0, border_noise + 18.0)
    strong = alpha & (
        ((saturation >= 0.14) & (distance >= colour_threshold))
        | (distance >= max(82.0, colour_threshold * 1.8))
    )
    if int(strong.sum()) < max(32, int(alpha.sum() * 0.035)):
        return alpha

    expanded = ndimage.binary_dilation(strong, iterations=3) & alpha
    expanded = ndimage.binary_fill_holes(expanded)
    return expanded


def apply_multiview_uv_texture(
    mesh,
    images: list[Image.Image],
    base_colour: np.ndarray,
    texture_size: int = 1024,
):
    """Bake canonical photographs into a portable CPU-generated UV atlas.

    Hunyuan Paint requires a custom CUDA rasterizer that is not generally
    buildable on Windows without the full CUDA SDK.  xatlas plus a small CPU
    baker preserves high-frequency markings in a normal embedded GLB texture,
    while normal-weighted blending avoids pasting the backdrop onto the mesh.
    """
    import xatlas
    from scipy import ndimage

    source_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    source_faces = np.asarray(mesh.faces, dtype=np.int64)
    if not len(source_vertices) or not len(source_faces) or not images:
        return apply_pbr_material(mesh, base_colour)

    vmapping, atlas_faces, uvs = xatlas.parametrize(source_vertices, source_faces)
    atlas_faces = np.asarray(atlas_faces, dtype=np.int64)
    uvs = np.asarray(uvs, dtype=np.float32)
    vertices = source_vertices[np.asarray(vmapping, dtype=np.int64)]
    source_normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    normals = source_normals[np.asarray(vmapping, dtype=np.int64)]

    bounds_min = source_vertices.min(axis=0)
    bounds_span = np.maximum(source_vertices.max(axis=0) - bounds_min, 1e-6)
    normalized = (vertices - bounds_min) / bounds_span
    view_specs = [
        (np.array([0.0, 0.0, 1.0], dtype=np.float32), 0, False),
        (np.array([-1.0, 0.0, 0.0], dtype=np.float32), 2, False),
        (np.array([0.0, 0.0, -1.0], dtype=np.float32), 0, True),
        (np.array([1.0, 0.0, 0.0], dtype=np.float32), 2, True),
    ]
    prepared_views = []
    depth_resolution = min(448, max(256, int(texture_size) // 3))
    for image, (camera_direction, horizontal_axis, flip_horizontal) in zip(
        images[:4], view_specs
    ):
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        alpha = _texture_subject_alpha(rgba)
        ys, xs = np.where(alpha)
        prepared_views.append(
            None
            if not len(xs)
            else (
                rgba,
                (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())),
                _rasterized_view_depth(
                    (source_vertices - bounds_min) / bounds_span,
                    source_faces,
                    camera_direction,
                    horizontal_axis,
                    flip_horizontal,
                    depth_resolution,
                ),
            )
        )

    size = int(np.clip(texture_size, 512, 2048))
    fallback = np.asarray(base_colour[:3], dtype=np.uint8)
    texture = np.repeat(fallback[None, None, :], size * size, axis=0).reshape(size, size, 3)
    painted = np.zeros((size, size), dtype=bool)
    texcoords = uvs.copy()
    texcoords[:, 0] *= size - 1
    texcoords[:, 1] = (1.0 - texcoords[:, 1]) * (size - 1)

    for face in atlas_faces:
        triangle = texcoords[face]
        x0 = max(0, int(np.floor(triangle[:, 0].min())))
        x1 = min(size - 1, int(np.ceil(triangle[:, 0].max())))
        y0 = max(0, int(np.floor(triangle[:, 1].min())))
        y1 = min(size - 1, int(np.ceil(triangle[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue
        grid_x, grid_y = np.meshgrid(
            np.arange(x0, x1 + 1, dtype=np.float32) + 0.5,
            np.arange(y0, y1 + 1, dtype=np.float32) + 0.5,
        )
        ax, ay = triangle[0]
        bx, by = triangle[1]
        cx, cy = triangle[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(float(denominator)) < 1e-8:
            continue
        wa = ((by - cy) * (grid_x - cx) + (cx - bx) * (grid_y - cy)) / denominator
        wb = ((cy - ay) * (grid_x - cx) + (ax - cx) * (grid_y - cy)) / denominator
        wc = 1.0 - wa - wb
        inside = (wa >= -1e-4) & (wb >= -1e-4) & (wc >= -1e-4)
        if not np.any(inside):
            continue
        pixel_x = grid_x[inside].astype(np.int32)
        pixel_y = grid_y[inside].astype(np.int32)
        barycentric = np.column_stack((wa[inside], wb[inside], wc[inside])).astype(np.float32)
        positions = barycentric @ normalized[face]
        pixel_normals = barycentric @ normals[face]
        pixel_normals /= np.maximum(np.linalg.norm(pixel_normals, axis=1, keepdims=True), 1e-7)
        accumulated = np.zeros((len(positions), 3), dtype=np.float32)
        total_weight = np.zeros(len(positions), dtype=np.float32)
        vertical = 1.0 - positions[:, 1]

        for prepared, (camera_direction, horizontal_axis, flip_horizontal) in zip(
            prepared_views, view_specs
        ):
            if prepared is None:
                continue
            rgba, (source_x0, source_x1, source_y0, source_y1), depth_map = prepared
            horizontal = positions[:, horizontal_axis]
            if flip_horizontal:
                horizontal = 1.0 - horizontal
            sample_x = source_x0 + horizontal * max(1, source_x1 - source_x0)
            sample_y = source_y0 + vertical * max(1, source_y1 - source_y0)
            sampled = _bilinear_rgba(rgba, sample_x, sample_y)
            facing = np.clip(pixel_normals @ camera_direction, 0.0, 1.0)
            visible = _visible_in_view(
                positions,
                camera_direction,
                horizontal_axis,
                flip_horizontal,
                depth_map,
            )
            # Grazing surfaces magnify a handful of source pixels into long
            # streaks. Leave those unobserved and use the coherent base
            # material instead of inventing photographic detail.
            valid = (sampled[:, 3] > 127) & visible & (facing >= 0.18)
            weight = np.where(valid, facing ** 3, 0.0).astype(np.float32)
            accumulated += sampled[:, :3] * weight[:, None]
            total_weight += weight

        covered = total_weight > 1e-5
        if not np.any(covered):
            continue
        colours = np.repeat(fallback[None, :].astype(np.float32), len(positions), axis=0)
        colours[covered] = accumulated[covered] / total_weight[covered, None]
        texture[pixel_y, pixel_x] = np.clip(np.rint(colours), 0, 255).astype(np.uint8)
        painted[pixel_y, pixel_x] = covered

    # Extend chart colours a few pixels across UV seams to prevent filtering
    # from revealing the neutral atlas background at chart borders.
    if np.any(painted):
        distance, indices = ndimage.distance_transform_edt(~painted, return_indices=True)
        padding = (~painted) & (distance <= 5.0)
        texture[padding] = texture[indices[0][padding], indices[1][padding]]

    atlas_mesh = trimesh.Trimesh(vertices=vertices, faces=atlas_faces, process=False)
    material = trimesh.visual.material.PBRMaterial(
        name="Multiview UV PBR material",
        baseColorTexture=Image.fromarray(texture, mode="RGB"),
        baseColorFactor=np.array([255, 255, 255, 255], dtype=np.uint8),
        metallicFactor=0.0,
        roughnessFactor=0.34,
    )
    atlas_mesh.visual = trimesh.visual.TextureVisuals(uv=uvs, material=material)
    return atlas_mesh
