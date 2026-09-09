import os
import sys
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from docx import Document
from pypdf import PdfWriter

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

DEFAULT_OUTPUT_NAME = "merged_output.pdf"

class DocumentMergerPlugin(BaseFileOperation):
    name = "Document Merger"
    description = "Merges .docx, .pdf, or text/markdown into one file (extension picks the engine)."
    supported_extensions = (".docx", ".pdf", ".txt", ".md")
    needs_output_dir = True

    def merge_docx(self, files, output_path):
        master = Document()
        master._body.clear_content()  # clear default empty paragraph
        for idx, file in enumerate(files):
            print(f"Adding DOCX: {file}")
            sub_doc = Document(file)
            for element in sub_doc.element.body:
                master.element.body.append(element)
            # Add page break between documents (except after the last file)
            if idx < len(files) - 1:
                master.add_page_break()
        master.save(output_path)

    def merge_pdf(self, files, output_path):
        merger = PdfWriter()
        for file in files:
            print(f"Adding PDF: {file}")
            merger.append(file)
        merger.write(output_path)
        merger.close()

    def merge_text(self, files, output_path):
        with open(output_path, "w", encoding="utf-8") as outfile:
            for file in files:
                print(f"Adding Text/MD: {file}")
                outfile.write(f"=== START OF FILE: {os.path.basename(file)} ===\n\n")
                with open(file, "r", encoding="utf-8", errors="ignore") as infile:
                    outfile.write(infile.read())
                outfile.write("\n\n=== END OF FILE ===\n\n\n")

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files found to merge.")

        output_ext = Path(output_path).suffix.lower()
        SUPPORTED_MAP = {
            ".docx": [".docx"],
            ".pdf": [".pdf"],
            ".txt": [".txt", ".md"],
            ".md": [".txt", ".md"]
        }

        if output_ext not in SUPPORTED_MAP:
            raise ValueError(f"Unsupported output format: {output_ext}. Please use an output extension ending in .docx, .pdf, .txt, or .md")

        allowed_inputs = SUPPORTED_MAP[output_ext]
        valid_files = [f for f in files if Path(f).suffix.lower() in allowed_inputs]

        if not valid_files:
            raise ValueError(f"No files match the allowed input types for output format {output_ext} (Allowed: {', '.join(allowed_inputs)})")

        os.makedirs(os.path.dirname(output_path) or os.getcwd(), exist_ok=True)
        print(f"Found {len(valid_files)} valid file(s) to process for {output_ext}.\n")

        if output_ext == ".docx":
            self.merge_docx(valid_files, output_path)
        elif output_ext == ".pdf":
            self.merge_pdf(valid_files, output_path)
        elif output_ext in [".txt", ".md"]:
            self.merge_text(valid_files, output_path)

        print(f"\nSuccessfully generated merged document: {output_path}")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Output file").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.output_name_var = tk.StringVar(value=DEFAULT_OUTPUT_NAME)
        ttk.Entry(frame, textvariable=self.output_name_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(
            frame,
            text="Ext (.pdf/.docx/.txt/.md) sets merge mode",
            style="SidebarMuted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        return frame

    def get_output_path(self, output_dir, files):
        name = getattr(self, "output_name_var", None)
        filename = name.get() if name else DEFAULT_OUTPUT_NAME
        return os.path.join(output_dir, filename)


def cli_main():
    if len(sys.argv) == 1:
        return
    parser = argparse.ArgumentParser(description="Merge documents (.docx, .pdf, .txt, .md)")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="")
    args = parser.parse_args()

    plugin = DocumentMergerPlugin()
    files = plugin.collect_input_files(args.inputs)
    if not files:
        print("No matching files found.")
        sys.exit(1)

    output_path = args.output.strip() or str(Path(files[0]).parent / DEFAULT_OUTPUT_NAME)
    output_ext = Path(output_path).suffix.lower()
    SUPPORTED_MAP = {
        ".docx": [".docx"],
        ".pdf": [".pdf"],
        ".txt": [".txt", ".md"],
        ".md": [".txt", ".md"],
    }
    allowed = SUPPORTED_MAP.get(output_ext, [".docx", ".pdf", ".txt", ".md"])
    valid = [f for f in files if Path(f).suffix.lower() in allowed]
    if not valid:
        print("No matching files for output type.")
        sys.exit(1)
    plugin.execute(valid, output_path)


if __name__ == "__main__":
    plugin_entry(DocumentMergerPlugin, cli_main)