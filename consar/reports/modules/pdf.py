from fpdf import FPDF
from fpdf.fonts import FontFace
from typing import List, Dict, Union
import datetime

class AforePDFReport(FPDF):
    def __init__(self, title_text, currency):
        super().__init__()
        self.title_text = title_text
        self.current_header_title = title_text # Allow dynamic changing
        self.currency = currency
        self.set_auto_page_break(auto=True, margin=15)
        # Add a page to start
        self.add_page()

    def set_header_title(self, title):
        """Update the title used in the header for subsequent pages."""
        self.current_header_title = title

    def header(self):
        # Logo or simple text header
        self.set_font('helvetica', 'B', 15)
        self.cell(0, 10, self.current_header_title, align='C')

        self.ln(10)

        self.set_font('helvetica', 'I', 10)
        self.cell(0, 5, f'Currency: {self.currency} | Generated: {datetime.date.today()}', align='C')
        self.ln(10)
        # Line break
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def chapter_title(self, label):
        self.set_font('helvetica', 'B', 12)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 6, label, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(4)

    def chapter_body(self, text):
        self.set_font('helvetica', '', 10)
        self.multi_cell(0, 5, text)
        self.ln()

    def add_table(self, header: List[str], data: List[List[Union[str, float]]], col_widths=None):
        """
        Renders a table using fpdf2's built-in table context manager.
        """
        self.set_font('helvetica', '', 9)

        with self.table(
            col_widths=col_widths,
            headings_style=FontFace(emphasis="BOLD", color=255, fill_color=(50, 50, 100)),
            line_height=6,
            text_align="CENTER",
            width=190
        ) as table:
            row = table.row()
            for h in header:
                row.cell(h)

            for row_data in data:
                row = table.row()

                # Check if this is the "Market Total" row to bold it
                is_market_total = "MARKET TOTAL" in str(row_data[0]).upper()

                for item in row_data:
                    item_str = str(item)

                    # Style settings
                    style = FontFace()
                    if is_market_total:
                        style.emphasis = "BOLD"
                        style.fill_color = (240, 240, 240)

                    # Check for negative numbers. Handles plain numbers AND
                    # compound cells like "$-34M (-4.4%)" / "-5.5%" (the old
                    # float() parse threw on those, silently skipping the red).
                    clean_str = item_str.replace('$', '').replace('%', '').replace(',', '').replace('M', '')
                    is_negative = clean_str.strip().startswith('-')
                    if not is_negative:
                        try:
                            is_negative = float(clean_str) < 0
                        except ValueError:
                            pass
                    if is_negative:
                        style.color = (200, 0, 0)  # Red

                    row.cell(item_str, style=style)
        self.ln(5)

    def add_image(self, image_path, width=170):
        self.image(image_path, w=width, x=(210-width)/2)
        self.ln(5)
