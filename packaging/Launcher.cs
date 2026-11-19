using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("DD Monitor Studio")]
[assembly: AssemblyDescription("DD Monitor Studio portable launcher")]
[assembly: AssemblyCompany("EricaNoir")]
[assembly: AssemblyProduct("DD Monitor Studio")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Launcher {
    [STAThread]
    private static void Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "python", "pythonw.exe");
            bool portable = File.Exists(python);
            if (!portable) python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
            if (!File.Exists(python)) throw new IOException("缺少运行时，请重新完整解压便携包。");
            var start = new ProcessStartInfo(python);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.Arguments = (portable ? "-I -B " : "-B ") + "\"" + Path.Combine(root, "studio_main.py") + "\"";
            if (Array.IndexOf(args, "--demo") >= 0) start.Arguments += " --demo";
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show(error.Message, "DD Monitor Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
