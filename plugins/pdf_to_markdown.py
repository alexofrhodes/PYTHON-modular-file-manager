import os
import sys
import io
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import pymupdf
import pdfplumber
import pytesseract
from PIL import Image
from docx import Document
from pptx2md import convert, ConversionConfig

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

PORTABLE_TESSERACT = Path(r"C:\Users\aanastasiou\Desktop\APPS\tesseract\tesseract.exe")


def resolve_tesseract() -> str | None:
    """PATH first, then known portable install; None if unavailable."""
    exe = shutil.which("tesseract")
    if exe:
        return exe
    if PORTABLE_TESSERACT.is_file():
        return str(PORTABLE_TESSERACT)
    return None


class PdfToMarkdownPlugin(BaseFileOperation):
    name = "Docs to Markdown"
    description = "Convert PDF / DOCX / PPTX to Markdown (PyMuPDF, pdfplumber, pymupdf4llm, OCR)."
    supported_extensions = (".pdf", ".docx", ".pptx")
    needs_output_dir = True

    def __init__(self):
        super().__init__()
        self.available_langs = ["eng", "ell", "fra", "deu", "spa", "ita"]
        self.tesseract_exe = resolve_tesseract()
        if self.tesseract_exe:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_exe

    def unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        i = 1
        base_stem = path.stem
        while True:
            p = path.with_name(f"{base_stem}_{i}{path.suffix}")
            if not p.exists():
                return p
            i += 1

    def parse_page_ranges(self, spec: str, max_pages: int) -> list:
        if not spec or not spec.strip():
            return list(range(max_pages))
        pages = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                for p in range(int(a), int(b) + 1):
                    pages.add(p - 1)
            else:
                pages.add(int(part) - 1)
        return sorted(p for p in pages if 0 <= p < max_pages)

    def extract_text_docx(self, docx_path: Path) -> str:
        """Convert DOCX to Markdown while preserving headings, bold/italic runs, and lists."""
        doc = Document(docx_path)
        lines = []

        def _run_md(run) -> str:
            text = run.text or ""
            if not text:
                return ""
            if run.bold and run.italic:
                return f"***{text}***"
            if run.bold:
                return f"**{text}**"
            if run.italic:
                return f"*{text}*"
            return text

        for paragraph in doc.paragraphs:
            style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
            body = "".join(_run_md(run) for run in paragraph.runs).strip()
            if not body and not paragraph.text.strip():
                lines.append("")
                continue
            if not body:
                body = paragraph.text.strip()

            if "heading 1" in style_name:
                lines.append(f"# {body}")
            elif "heading 2" in style_name:
                lines.append(f"## {body}")
            elif "heading 3" in style_name:
                lines.append(f"### {body}")
            elif "heading 4" in style_name:
                lines.append(f"#### {body}")
            elif "list" in style_name:
                lines.append(f"- {body}")
            else:
                lines.append(body)

        return "\n\n".join(lines).strip()

    def extract_text_pymupdf(self, pdf: Path) -> str:
        doc = pymupdf.open(pdf)
        text = "\n".join(page.get_text("text") or "" for page in doc)
        doc.close()
        return text.strip()

    def extract_text_pdfplumber(self, pdf: Path) -> str:
        parts = []
        with pdfplumber.open(pdf) as pdfd:
            for p in pdfd.pages:
                parts.append(p.extract_text() or "")
        return "\n".join(parts).strip()

    def extract_text_pymupdf4llm(self, pdf: Path) -> str:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(str(pdf))

    def ocr_pdf(self, pdf: Path, pages: list, lang: str) -> str:
        exe = self.tesseract_exe or resolve_tesseract()
        if not exe:
            return "[OCR Error: Tesseract not found (PATH or portable install)]"
        pytesseract.pytesseract.tesseract_cmd = exe
        try:
            doc = pymupdf.open(pdf)
        except Exception as e:
            return f"[OCR Error opening document: {e}]"
            
        parts = []
        for i in pages:
            try:
                pix = doc[i].get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                parts.append(pytesseract.image_to_string(img, lang=lang))
            except Exception as e:
                parts.append(f"[OCR Error on page {i+1}: {e}]")
        doc.close()
        return "\n\n--- PAGE BREAK ---\n\n".join(parts).strip()

    def process_pptx_file(self, file_path: Path, out_dir: Path, pptx_opts: dict) -> str:
        temp_md = out_dir / f"~temp_{file_path.name}.md"
        img_dir = out_dir / f"{file_path.stem}_img"
        
        kwargs = {
            "pptx_path": file_path,
            "output_path": temp_md,
            "image_dir": img_dir,
            "disable_image": pptx_opts.get("disable_image", False),
            "disable_escaping": pptx_opts.get("disable_escaping", False),
            "disable_notes": pptx_opts.get("disable_notes", True),
            "disable_wmf": pptx_opts.get("disable_wmf", False),
            "disable_color": pptx_opts.get("disable_color", False),
            "enable_slides": pptx_opts.get("enable_slides", False),
            "try_multi_column": pptx_opts.get("try_multi_column", False),
            "keep_similar_titles": pptx_opts.get("keep_similar_titles", False),
        }

        if str(pptx_opts.get("image_width", "")).isdigit():
            kwargs["image_width"] = int(pptx_opts["image_width"])
        if str(pptx_opts.get("min_block_size", "")).isdigit():
            kwargs["min_block_size"] = int(pptx_opts["min_block_size"])

        if kwargs["disable_image"] is False:
            img_dir.mkdir(parents=True, exist_ok=True)

        convert(ConversionConfig(**kwargs))

        content = ""
        if temp_md.exists():
            content = temp_md.read_text(encoding="utf-8")
            temp_md.unlink()

        return content

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No input files provided.")

        # Read configuration from UI variables bound to self
        m1 = getattr(self, "m1_var", tk.BooleanVar(value=True)).get()
        m2 = getattr(self, "m2_var", tk.BooleanVar(value=False)).get()
        m3 = getattr(self, "m3_var", tk.BooleanVar(value=False)).get()
        m_ocr = getattr(self, "m_ocr_var", tk.BooleanVar(value=False)).get()
        if m_ocr and not (self.tesseract_exe or resolve_tesseract()):
            print("OCR skipped: Tesseract not found (PATH or portable install).")
            m_ocr = False

        methods = []
        if m1:
            methods.append("1")
        if m2:
            methods.append("2")
        if m3:
            methods.append("3")
        if m_ocr:
            methods.append("ocr")

        if not methods:
            methods = ["1"]

        combine = getattr(self, "combine_var", tk.BooleanVar(value=False)).get()
        combine_name = getattr(self, "combine_name_var", tk.StringVar(value="output.md")).get()
        overwrite = getattr(self, "overwrite_var", tk.BooleanVar(value=True)).get()

        selected_lang_indices = getattr(self, "lang_listbox", None)
        selected_langs = ["eng", "ell"]
        if selected_lang_indices:
            try:
                indices = selected_lang_indices.curselection()
                if indices:
                    selected_langs = [self.available_langs[i] for i in indices]
            except Exception:
                pass
        ocr_lang_str = "+".join(selected_langs)
        ocr_pages_str = getattr(self, "ocr_pages_var", tk.StringVar(value="")).get()

        pptx_opts = {}
        if hasattr(self, "pptx_flags"):
            pptx_opts = {k: v.get() for k, v in self.pptx_flags.items()}
        if hasattr(self, "pptx_img_width_var"):
            pptx_opts["image_width"] = self.pptx_img_width_var.get()
        if hasattr(self, "pptx_min_block_var"):
            pptx_opts["min_block_size"] = self.pptx_min_block_var.get()

        extractors = {
            "1": ("pymupdf", self.extract_text_pymupdf),
            "2": ("pdfplumber", self.extract_text_pdfplumber),
            "3": ("pymupdf4llm", self.extract_text_pymupdf4llm),
        }

        base_out_dir = Path(output_path if os.path.isdir(output_path) else os.path.dirname(output_path))
        base_out_dir.mkdir(parents=True, exist_ok=True)

        for method in methods:
            combined_buffer = []
            pdf_suffix = extractors[method][0] if method in extractors else ("ocr" if method == "ocr" else "converted")

            for file_path_str in files:
                file_path = Path(file_path_str)
                if not file_path.exists():
                    continue

                is_pdf = file_path.suffix.lower() == ".pdf"
                
                # Prevent non-PDF files from executing multiple times across different PDF engines
                if not is_pdf and method != methods[0] and not combine:
                    continue

                suffix = pdf_suffix if is_pdf else file_path.suffix.lower()[1:]
                print(f"Processing [{file_path.suffix.upper()}] with engine ({suffix}): {file_path.name}")
                
                try:
                    content = ""
                    if file_path.suffix.lower() == ".docx":
                        content = self.extract_text_docx(file_path)
                    elif file_path.suffix.lower() == ".pptx":
                        content = self.process_pptx_file(file_path, base_out_dir, pptx_opts)
                    else:
                        if method in extractors:
                            _, fn = extractors[method]
                            content = fn(file_path)
                        elif method == "ocr":
                            doc = pymupdf.open(file_path)
                            pages = self.parse_page_ranges(ocr_pages_str, doc.page_count)
                            doc.close()
                            content = self.ocr_pdf(file_path, pages, ocr_lang_str)

                    if combine:
                        # Add structural divider headers inside the file merger
                        header = f"# Source: {file_path.name}\n\n"
                        combined_buffer.append(f"{header}{content}")
                    else:
                        dest_path = base_out_dir / f"{file_path.stem} ({suffix}).md"
                        if not overwrite:
                            dest_path = self.unique_path(dest_path)
                        dest_path.write_text(content, encoding="utf-8")
                except Exception as e:
                    print(f"Error processing {file_path.name}: {e}")

            if combine and combined_buffer:
                if len(methods) > 1:
                    name_part = Path(combine_name)
                    final_comb_name = f"{name_part.stem} ({pdf_suffix}){name_part.suffix}"
                else:
                    final_comb_name = combine_name

                final_path = base_out_dir / final_comb_name
                if not overwrite:
                    final_path = self.unique_path(final_path)
                
                # Join unified text stream with standard markdown spacing rules
                final_path.write_text("\n\n---\n\n".join(combined_buffer), encoding="utf-8")
                print(f"Combined output written to: {final_path}")

        print("PDF to Markdown conversion batch completed successfully.")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        notebook = ttk.Notebook(parent_frame)

        tab_gen = ttk.Frame(notebook, padding=4)
        notebook.add(tab_gen, text="Engines")

        self.m1_var = tk.BooleanVar(value=True)
        self.m2_var = tk.BooleanVar(value=False)
        self.m3_var = tk.BooleanVar(value=False)
        self.m_ocr_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(tab_gen, text="PyMuPDF", variable=self.m1_var).pack(anchor=tk.W)
        ttk.Checkbutton(tab_gen, text="pdfplumber", variable=self.m2_var).pack(anchor=tk.W)
        ttk.Checkbutton(tab_gen, text="pymupdf4llm", variable=self.m3_var).pack(anchor=tk.W)
        ocr_cb = ttk.Checkbutton(tab_gen, text="OCR (Tesseract)", variable=self.m_ocr_var)
        ocr_cb.pack(anchor=tk.W)
        if not self.tesseract_exe:
            self.m_ocr_var.set(False)
            ocr_cb.configure(state="disabled")

        ttk.Separator(tab_gen, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self.combine_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_gen, text="Combine to one .md", variable=self.combine_var).pack(anchor=tk.W)
        self.combine_name_var = tk.StringVar(value="output.md")
        ttk.Entry(tab_gen, textvariable=self.combine_name_var).pack(fill=tk.X, pady=2)
        self.overwrite_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab_gen, text="Overwrite", variable=self.overwrite_var).pack(anchor=tk.W)

        tab_pptx = ttk.Frame(notebook, padding=4)
        notebook.add(tab_pptx, text="PPTX")
        self.pptx_flags = {
            "disable_image": tk.BooleanVar(value=False),
            "disable_escaping": tk.BooleanVar(value=False),
            "disable_notes": tk.BooleanVar(value=True),
            "disable_wmf": tk.BooleanVar(value=False),
            "disable_color": tk.BooleanVar(value=False),
            "enable_slides": tk.BooleanVar(value=False),
            "try_multi_column": tk.BooleanVar(value=False),
            "keep_similar_titles": tk.BooleanVar(value=False),
        }
        for flag_name, var_obj in self.pptx_flags.items():
            ttk.Checkbutton(tab_pptx, text=flag_name, variable=var_obj).pack(anchor=tk.W)
        row = ttk.Frame(tab_pptx)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Img w").pack(side=tk.LEFT)
        self.pptx_img_width_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.pptx_img_width_var, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="Min blk").pack(side=tk.LEFT)
        self.pptx_min_block_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.pptx_min_block_var, width=6).pack(side=tk.LEFT, padx=4)

        tab_ocr = ttk.Frame(notebook, padding=4)
        notebook.add(tab_ocr, text="OCR")
        if not self.tesseract_exe:
            ttk.Label(
                tab_ocr,
                text="Tesseract not found.\nInstall on PATH or place portable at:\n"
                + str(PORTABLE_TESSERACT),
                wraplength=280,
            ).pack(anchor=tk.W)
        self.lang_listbox = tk.Listbox(tab_ocr, selectmode=tk.MULTIPLE, height=4, exportselection=0, font=("Segoe UI", 8))
        for lang in self.available_langs:
            self.lang_listbox.insert(tk.END, lang)
        self.lang_listbox.selection_set(0)
        self.lang_listbox.selection_set(1)
        self.lang_listbox.pack(fill=tk.X)
        ttk.Label(tab_ocr, text="Pages (1-3,5)").pack(anchor=tk.W, pady=(4, 0))
        self.ocr_pages_var = tk.StringVar(value="")
        ocr_pages_entry = ttk.Entry(tab_ocr, textvariable=self.ocr_pages_var)
        ocr_pages_entry.pack(fill=tk.X, pady=2)
        if not self.tesseract_exe:
            self.lang_listbox.configure(state="disabled")
            ocr_pages_entry.configure(state="disabled")

        return notebook

    def get_output_path(self, output_dir, files):
        return output_dir


def _cli_default_outdir(files):
    if files:
        return str(Path(files[0]).parent)
    return str(Path.cwd())


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert PDF / DOCX / PPTX to Markdown")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="")
    parser.add_argument(
        "--engine",
        choices=["1", "2", "3", "ocr"],
        default="1",
        help="PDF engine",
    )
    parser.add_argument("--combine", action="store_true")
    args = parser.parse_args()

    plugin = PdfToMarkdownPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files found.")
        sys.exit(1)

    if args.engine == "ocr" and not plugin.tesseract_exe:
        print(
            "Tesseract not found (PATH or portable):\n"
            f"  {PORTABLE_TESSERACT}"
        )
        sys.exit(1)

    out_dir = args.output.strip() or _cli_default_outdir(files)
    plugin.m1_var = tk.BooleanVar(value=args.engine == "1")
    plugin.m2_var = tk.BooleanVar(value=args.engine == "2")
    plugin.m3_var = tk.BooleanVar(value=args.engine == "3")
    plugin.m_ocr_var = tk.BooleanVar(value=args.engine == "ocr")
    plugin.combine_var = tk.BooleanVar(value=args.combine)
    plugin.combine_name_var = tk.StringVar(value="output.md")
    plugin.overwrite_var = tk.BooleanVar(value=True)
    plugin.execute(files, out_dir)


if __name__ == "__main__":
    plugin_entry(PdfToMarkdownPlugin, cli_main)