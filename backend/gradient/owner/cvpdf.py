"""Render a CV dict to a one-column, ATS-friendly PDF (plain text layer, no tables or images)."""

from fpdf import FPDF

_REPLACE = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
            "•": "-", "…": "...", " ": " ", "→": "->", "²": "2"}


def _t(text: str) -> str:
    """Core PDF fonts are Latin-1; map common typography and drop anything else."""
    text = "".join(_REPLACE.get(c, c) for c in str(text or ""))
    return text.encode("latin-1", "ignore").decode("latin-1")


class _Doc(FPDF):
    def section(self, title: str) -> None:
        self.ln(2.5)
        self.set_font("Helvetica", "B", 10.5)
        self.set_text_color(20, 20, 20)
        self.cell(0, 6, _t(title.upper()), new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(160, 160, 160)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(1.5)

    def bullet(self, text: str) -> None:
        self.set_font("Helvetica", "", 9.5)
        x = self.l_margin
        self.set_x(x + 2)
        self.cell(4, 4.6, "-")
        self.multi_cell(self.w - self.r_margin - x - 6, 4.6, _t(text), new_x="LMARGIN", new_y="NEXT")

    def heading_row(self, left: str, right: str = "", sub: str = "") -> None:
        self.set_font("Helvetica", "B", 10)
        width = self.w - self.l_margin - self.r_margin
        self.cell(width * 0.72, 5.2, _t(left))
        self.set_font("Helvetica", "", 9.5)
        self.cell(width * 0.28, 5.2, _t(right), align="R", new_x="LMARGIN", new_y="NEXT")
        if sub:
            self.set_font("Helvetica", "I", 9.5)
            self.cell(0, 4.8, _t(sub), new_x="LMARGIN", new_y="NEXT")


def render(cv: dict) -> bytes:
    pdf = _Doc(format="A4")
    pdf.set_margins(14, 12, 14)
    pdf.set_auto_page_break(True, 12)
    pdf.add_page()
    pdf.set_title(_t(f"{cv.get('name', '')} - CV"))

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 9, _t(cv.get("name", "")), new_x="LMARGIN", new_y="NEXT")
    c = cv.get("contact", {})
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(0, 5, _t("  |  ".join(x for x in (cv.get("headline"), c.get("location"), c.get("email"), c.get("phone")) if x)),
             new_x="LMARGIN", new_y="NEXT")
    links = c.get("links") or []
    if links:
        pdf.set_text_color(30, 80, 160)
        for i, (label, url) in enumerate(links):
            pdf.cell(pdf.get_string_width(_t(label)) + 1, 5, _t(label), link=url)
            if i < len(links) - 1:
                pdf.set_text_color(20, 20, 20)
                pdf.cell(6, 5, "  |  ")
                pdf.set_text_color(30, 80, 160)
        pdf.ln(5)
        pdf.set_text_color(20, 20, 20)

    if cv.get("summary"):
        pdf.section("Summary")
        pdf.set_font("Helvetica", "", 9.5)
        pdf.multi_cell(0, 4.6, _t(cv["summary"]), new_x="LMARGIN", new_y="NEXT")

    if cv.get("skills"):
        pdf.section("Skills")
        pdf.set_font("Helvetica", "", 9.5)
        pdf.multi_cell(0, 4.6, _t(", ".join(cv["skills"])), new_x="LMARGIN", new_y="NEXT")

    if cv.get("experience"):
        pdf.section("Experience")
        for e in cv["experience"]:
            pdf.heading_row(f"{e['title']}, {e['org']}", e.get("dates", ""))
            for b in e.get("bullets", []):
                pdf.bullet(b)
            pdf.ln(1)

    if cv.get("projects"):
        pdf.section("Projects")
        for p in cv["projects"]:
            pdf.heading_row(p["title"], p.get("dates", ""))
            for b in p.get("bullets", []):
                pdf.bullet(b)
            pdf.ln(1)

    if cv.get("education"):
        pdf.section("Education")
        for ed in cv["education"]:
            pdf.heading_row(ed["school"], ed.get("dates", ""), ed.get("degree", ""))

    if cv.get("achievements"):
        pdf.section("Achievements")
        for a in cv["achievements"]:
            pdf.bullet(a)

    return bytes(pdf.output())
