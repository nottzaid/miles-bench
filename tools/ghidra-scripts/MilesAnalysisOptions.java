// Pre-script for analyzeHeadless: keep the analyzers that find functions (PE .pdata, entry points,
// disassembly) and name things (RTTI, strings), drop the ones that are slow on a 144 MiB image.
import ghidra.app.script.GhidraScript;
import java.util.Map;

public class MilesAnalysisOptions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] off = {
            "Decompiler Parameter ID", "Decompiler Switch Analysis", "Stack", "Call Convention ID",
            "Non-Returning Functions - Discovered", "Embedded Media", "DWARF", "Aggressive Instruction Finder",
            "Function ID", "Library Identification", "Condense Filler Bytes", "Create Address Tables",
            "Variadic Function Signature Override", "Call-Fixup Installer", "Shared Return Calls",
        };
        Map<String, String> opts = getCurrentAnalysisOptionsAndValues(currentProgram);
        for (String name : off) {
            if (opts.containsKey(name)) {
                setAnalysisOption(currentProgram, name, "false");
                println("analysis off: " + name);
            }
        }
    }
}
