import java.io.File
import kotlin.math.*
import org.umamo.format.cmo3.Cmo3
import org.umamo.format.cmo3.model.custom.CModelSource
import org.umamo.format.cmo3.model.gen.*
import org.umamo.interop.cmo3.*
import org.umamo.interop.ExportNotice
import org.umamo.render.eval.drawableSpaceMapping
import org.umamo.render.eval.CpuDeformationEvaluator
import org.umamo.runtime.model.*
import io.github.psd2live.targets.cubism.PuppetIr
import io.github.psd2live.targets.cubism.Moc3Target
import io.github.psd2live.targets.runtime.P2lrt
import io.github.psd2live.format.model.Bytes
import io.github.psd2live.format.model.TexturePage
import io.github.psd2live.format.model.ParameterRole
import io.github.psd2live.format.compile.ExportOptions
import io.github.psd2live.format.compile.FrameSpec
import io.github.psd2live.format.compile.PngEncoder
import io.github.psd2live.core.IrFrameRenderer

/** Reuse one authored eye's art and mesh for the pair, inside the actual Cubism model. */
fun main(args: Array<String>) {
    val source = Cmo3.read(File(args[0]))
    val root = source.root as CModelSource
    val model = Cmo3Import.fromModelSource(root)
    val neutral = model.parameters.associate { it.id to it.default }
    val dx = 142f
    val dy = -34f
    val length = hypot(dx, dy)
    val nx = dx / length
    val ny = dy / length
    val eyeCenterX = 446.406f
    val eyeCenterY = 430.413f
    val axisX = eyeCenterX + dx / 2
    val axisY = eyeCenterY + dy / 2
    fun remapId(id: ParameterId) = ParameterId(id.raw.replace("ParamEyeLOpen", "ParamEyeROpen"))
    fun <T> remapGrid(grid: KeyformGrid<T>) = KeyformGrid(
        grid.axes.map { KeyformAxis(remapId(it.parameterId), it.keys.copyOf()) }, grid.cells)
    val reports = mutableListOf<String>()
    val replacements = mutableMapOf<DrawableId, Drawable>()
    for (kind in listOf("Eyewhite", "Eyelash", "Irides")) {
        val left = model.drawables.single { it.id.raw == "ArtMesh${kind}L" }
        val right = model.drawables.single { it.id.raw == "ArtMesh${kind}R" }
        val leftMesh = requireNotNull(left.mesh)
        val leftSpace = requireNotNull(drawableSpaceMapping(model, neutral, left.id))
        val rightSpace = requireNotNull(drawableSpaceMapping(model, neutral, right.id))
        val reflect = kind != "Irides" // Both irises retain the same light/highlight direction.
        fun transformCanvas(points: FloatArray): FloatArray {
            val canvas = points.copyOf()
            for (i in canvas.indices step 2) {
                val x = canvas[i]; val y = canvas[i + 1]
                if (reflect) {
                    val distance = (x - axisX) * nx + (y - axisY) * ny
                    canvas[i] = x - 2 * distance * nx
                    canvas[i + 1] = y - 2 * distance * ny
                } else { canvas[i] = x + dx; canvas[i + 1] = y + dy }
            }
            return canvas
        }
        fun transformed(points: FloatArray): FloatArray {
            val world = leftSpace.localToWorld(points)
            for (i in world.indices step 2) {
                val x = world[i]
                val y = -world[i + 1]
                if (reflect) {
                    val distance = (x - axisX) * nx + (y - axisY) * ny
                    world[i] = x - 2 * distance * nx
                    world[i + 1] = -(y - 2 * distance * ny)
                } else {
                    world[i] = x + dx
                    world[i + 1] = -(y + dy)
                }
            }
            val local = rightSpace.worldToLocal(world, FloatArray(points.size) { .5f }, (0 until points.size / 2).toSet())
            val reached = rightSpace.localToWorld(local)
            val error = reached.indices.maxOf { abs(reached[it] - world[it]) }
            require(error < .05f) { "Cannot place $kind into right parent: $error px" }
            return local
        }
        // CMO3 stores editable rest bases in canvas space, while base+delta is parent-local.
        val newBase = transformCanvas(leftMesh.positions)
        val newGeometry = left.geometryGrid?.let { grid ->
            KeyformGrid(grid.axes.map { KeyformAxis(remapId(it.parameterId), it.keys.copyOf()) }, grid.cells.map { cell ->
                val posed = FloatArray(leftMesh.positions.size) { leftMesh.positions[it] + cell.form.positionDeltas[it] }
                val transformed = transformed(posed)
                KeyformCell(cell.coordinate.copyOf(), MeshDeltaForm(FloatArray(newBase.size) { transformed[it] - newBase[it] }))
            })
        }
        val indices = leftMesh.indices.copyOf()
        if (reflect) for (i in indices.indices step 3) {
            val old = indices[i + 1]; indices[i + 1] = indices[i + 2]; indices[i + 2] = old
        }
        replacements[right.id] = right.copy(
            mesh = DrawableMesh(newBase, leftMesh.uvs.copyOf(), indices),
            geometryGrid = newGeometry,
            channelGrids = ChannelGrids(left.channelGrids.gridsByChannel.mapValues { remapGrid(it.value) }),
            textureSourceId = null, texturePage = left.texturePage, atlasTileId = left.atlasTileId,
            blendShapes = emptyList(), culling = false)
        reports += "$kind: same source art, same vertex/UV inventory, ${leftMesh.vertexCount} vertices; ${if(reflect) "reflected on tilted facial midline" else "translated without reversing highlights"}"
    }
    val paired = model.copy(drawables = model.drawables.map { replacements[it.id] ?: it })
    // Author independent native image placements for the shared art. This also creates a correct
    // geometry/UV weld for the mirrored eye, so re-atlasing in Cubism remains editable.
    val textures = cmo3AtlasPages(root, source::extractLayerPng)
    val pages = textures.pageBytes.map { bytes ->
        val image = javax.imageio.ImageIO.read(bytes.inputStream())
        Cmo3Conversion.AtlasPage(bytes, image.width, image.height)
    }
    if (args.size > 3) {
        val output = File(args[3]).apply { mkdirs() }
        val bindings = textures.atlasIndexByDrawableId.toMutableMap()
        for (kind in listOf("Eyewhite", "Eyelash", "Irides"))
            bindings["ArtMesh${kind}R"] = bindings.getValue("ArtMesh${kind}L")
        val roles = listOf(ParameterRole("EyeBlink", listOf("ParamEyeLOpen", "ParamEyeROpen")),
            ParameterRole("AngleX", listOf("ParamAngleX")), ParameterRole("AngleY", listOf("ParamAngleY")),
            ParameterRole("EyeBallX", listOf("ParamEyeBallX")), ParameterRole("EyeBallY", listOf("ParamEyeBallY")))
        val runtimeModel = paired.copy(drawables = paired.drawables.map { it.copy(texturePage = bindings.getValue(it.id.raw)) })
        val ir = PuppetIr.toIr(runtimeModel, pages.map { TexturePage(it.width, it.height, Bytes.wrap(it.pngBytes)) }, bindings,
            parameterRoles = roles)
        File(output, "yunque.p2lrt").writeBytes(P2lrt.write(ir))
        val native = Moc3Target.plan(ir, ExportOptions("yunque-symmetric"))
        require(native.losses.isEmpty()) { "Runtime export loses model data: ${native.losses}" }
        native.write { path, bytes -> File(output, path).apply { parentFile.mkdirs(); writeBytes(bytes) } }
        IrFrameRenderer.open(ir, false).use { session ->
            val image = session.render(emptyMap(), 0f, FrameSpec(170f, 0f, 700f, 640f, 875, 800, 0xfff3f7fc.toInt()))
            File(output, "yunque-head-preview.png").writeBytes(PngEncoder.encode(image.width, image.height, image.argb))
        }
        reports += "Runtime reuses ${pages.size} original atlas page(s) byte-for-byte; no downsampling of the character."
        println("Original atlas pages=${pages.size}; UVs address pages=${model.atlas.storedUvsAddressPages}")
    }
    val detached = paired.copy(atlas = PuppetAtlas.Empty, sources = emptyList(), drawables = paired.drawables.map {
        val sourceId = if(it.id.raw.endsWith("R") && it.id in replacements) it.id.raw.dropLast(1)+"L" else it.id.raw
        it.copy(atlasTileId = null, textureSourceId = null, texturePage = textures.atlasIndexByDrawableId.getValue(sourceId))
    })
    val converted = Cmo3Conversion.freshCmo3(detached, pages,
        detached.drawables.associate { it.id.raw to it.texturePage }, "云雀 · 对称眼型", System.currentTimeMillis(), 0)
    val report = converted.report
    println("CMO3 notices: ${report.notices}")
    require(report.notices.all { it is ExportNotice.MissingSourceArt }) { "The native export could not retain all model edits" }
    reports += "Native layer patches reconstructed from retained atlas pixels; original high-resolution source artwork remains in the v2 project."
    Cmo3.write(converted.model, File(args[1]))
    // Check the actual emitted artifact, not just the in-memory candidate.
    val roundtrip = Cmo3Import.fromModelSource(Cmo3.read(File(args[1])).root as CModelSource)
    val expectedPose = CpuDeformationEvaluator().evaluate(paired, neutral)
    val actualPose = CpuDeformationEvaluator().evaluate(roundtrip, neutral)
    for ((id, expected) in replacements) {
        val actual = roundtrip.drawables.single { it.id == id }
        require(actual.mesh!!.vertexCount == expected.mesh!!.vertexCount)
        val expectedWorld = expectedPose.worldPositions.getValue(id)
        val actualWorld = actualPose.worldPositions.getValue(id)
        val error = actualWorld.indices.maxOf { abs(actualWorld[it] - expectedWorld[it]) }
        require(error < .05f) { "Native roundtrip changed $id: $error px" }
        reports += "${id.raw}: native roundtrip placement error $error px"
    }
    File(args[2]).writeText(reports.joinToString("\n", postfix="\n"))
    println(reports.joinToString("\n"))
}
