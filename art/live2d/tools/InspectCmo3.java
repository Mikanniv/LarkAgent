import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import org.umamo.format.cmo3.Cmo3;
import org.umamo.format.cmo3.model.custom.CModelSource;
import org.umamo.interop.cmo3.Cmo3Import;

/** Read-only inspection of the authored Cubism container. */
class InspectCmo3 {
    public static void main(String[] args) throws Exception {
        var model = Cmo3.INSTANCE.read(new File(args[0]));
        var puppet = Cmo3Import.INSTANCE.fromModelSource((CModelSource) model.getRoot(), true);
        for (var drawable : puppet.getDrawables()) {
            if (!drawable.getName().matches(".*(Lashes|Iris).*")) continue;
            var points = drawable.getMesh().getPositions();
            float left=Float.POSITIVE_INFINITY, top=left, right=Float.NEGATIVE_INFINITY, bottom=right;
            for (int i=0; i<points.length; i+=2) {
                left=Math.min(left, points[i]); right=Math.max(right, points[i]);
                top=Math.min(top, points[i+1]); bottom=Math.max(bottom, points[i+1]);
            }
            System.out.println(drawable.getName()+" local bounds: "+left+", "+top+", "+right+", "+bottom);
        }
        for (var entry : model.getArchive().getEntries()) {
            if (entry.getTag().equals("main_xml")) {
                Files.write(Path.of(args[1]), entry.getContent());
                System.out.println("Decoded authoring XML for inspection.");
                return;
            }
        }
        throw new IllegalStateException("No model XML in CMO3");
    }
}
