"""Build small AcroForms with real-world structures for regression tests.

Covers what the synthetic corpus does not: hierarchical (parent/kid) field
names, radio groups, ``/MaxLen`` limits, and required flags on buttons.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

REQUIRED = 0x02
RADIO_FLAGS = 0x8000 | 0x4000  # Radio | NoToggleToOff


class FormBuilder:
    def __init__(self, pages: int = 1) -> None:
        self.writer = PdfWriter()
        self.pages = [self.writer.add_blank_page(width=612, height=792) for _ in range(pages)]
        for page in self.pages:
            page[NameObject("/Annots")] = ArrayObject()
        font = self.writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        self.acro_form = DictionaryObject(
            {
                NameObject("/Fields"): ArrayObject(),
                NameObject("/NeedAppearances"): BooleanObject(True),
                NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"),
                NameObject("/DR"): DictionaryObject(
                    {NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font})}
                ),
            }
        )
        self.writer._root_object[NameObject("/AcroForm")] = self.acro_form
        self._y = 700

    def _rect(self) -> ArrayObject:
        self._y -= 30
        return ArrayObject([NumberObject(n) for n in (100, self._y, 300, self._y + 20)])

    def _widget(self, page: int, extra: dict) -> DictionaryObject:
        widget = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/Rect"): self._rect(),
                NameObject("/F"): NumberObject(4),
                NameObject("/P"): self.pages[page].indirect_reference,
                **extra,
            }
        )
        return widget

    def text(
        self,
        name: str,
        *,
        page: int = 0,
        required: bool = False,
        max_len: int | None = None,
        parent: str | None = None,
    ) -> FormBuilder:
        extra = {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Ff"): NumberObject(REQUIRED if required else 0),
            NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g"),
        }
        if max_len is not None:
            extra[NameObject("/MaxLen")] = NumberObject(max_len)
        ref = self.writer._add_object(self._widget(page, extra))
        self.pages[page][NameObject("/Annots")].append(ref)
        if parent is None:
            self.acro_form[NameObject("/Fields")].append(ref)
        else:
            parent_ref = self._parent(parent)
            ref.get_object()[NameObject("/Parent")] = parent_ref
            parent_ref.get_object()[NameObject("/Kids")].append(ref)
        return self

    def _parent(self, name: str):
        for ref in self.acro_form["/Fields"]:
            obj = ref.get_object()
            if obj.get("/T") == name and "/Kids" in obj:
                return ref
        ref = self.writer._add_object(
            DictionaryObject(
                {NameObject("/T"): TextStringObject(name), NameObject("/Kids"): ArrayObject()}
            )
        )
        self.acro_form[NameObject("/Fields")].append(ref)
        return ref

    def checkbox(self, name: str, *, page: int = 0, required: bool = False) -> FormBuilder:
        ref = self.writer._add_object(
            self._widget(
                page,
                {
                    NameObject("/FT"): NameObject("/Btn"),
                    NameObject("/T"): TextStringObject(name),
                    NameObject("/Ff"): NumberObject(REQUIRED if required else 0),
                    NameObject("/V"): NameObject("/Off"),
                    NameObject("/AS"): NameObject("/Off"),
                    NameObject("/AP"): DictionaryObject(
                        {
                            NameObject("/N"): DictionaryObject(
                                {
                                    NameObject("/Yes"): DictionaryObject(),
                                    NameObject("/Off"): DictionaryObject(),
                                }
                            )
                        }
                    ),
                },
            )
        )
        self.pages[page][NameObject("/Annots")].append(ref)
        self.acro_form[NameObject("/Fields")].append(ref)
        return self

    def radio(
        self, name: str, options: list[str], *, page: int = 0, required: bool = False
    ) -> FormBuilder:
        group_ref = self.writer._add_object(
            DictionaryObject(
                {
                    NameObject("/FT"): NameObject("/Btn"),
                    NameObject("/T"): TextStringObject(name),
                    NameObject("/Ff"): NumberObject(RADIO_FLAGS | (REQUIRED if required else 0)),
                    NameObject("/V"): NameObject("/Off"),
                    NameObject("/Kids"): ArrayObject(),
                }
            )
        )
        for option in options:
            kid = self._widget(
                page,
                {
                    NameObject("/Parent"): group_ref,
                    NameObject("/AS"): NameObject("/Off"),
                    NameObject("/AP"): DictionaryObject(
                        {
                            NameObject("/N"): DictionaryObject(
                                {
                                    NameObject("/" + option): DictionaryObject(),
                                    NameObject("/Off"): DictionaryObject(),
                                }
                            )
                        }
                    ),
                },
            )
            kid_ref = self.writer._add_object(kid)
            group_ref.get_object()[NameObject("/Kids")].append(kid_ref)
            self.pages[page][NameObject("/Annots")].append(kid_ref)
        self.acro_form[NameObject("/Fields")].append(group_ref)
        return self

    def save(self, path: Path) -> Path:
        with path.open("wb") as handle:
            self.writer.write(handle)
        return path
