"""Extracted information with confidence scores, editable for manual correction."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.poker.ranges import PRESETS
from app.state.model import STREETS, Action, Field, GameState, Player
from app.state.positions import POSITION_CODES, label as position_label
from app.state.text_format import describe_actions

from . import theme
from .card_picker import CardPicker
from .widgets import AmountEdit, CardButton, ConfidenceBadge, labeled_row

UNKNOWN_FIELD = lambda: Field(None, 1.0, "manual")  # noqa: E731  the user says: unknown


def _style_for(field: Field, threshold: float) -> str:
    color = theme.confidence_color(field.confidence, field.known, threshold)
    if field.source == "manual":
        color = theme.INFO if field.known else theme.UNKNOWN_GREY
    return f"border: 1px solid {color};"


class CorrectionPanel(QWidget):
    stateEdited = Signal()
    cardCorrected = Signal(str, int, str)  # ("hero" | "board", index, card code)
    rangeChanged = Signal()

    def __init__(self, threshold: float = 0.7, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.threshold = threshold
        self.state = GameState()
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(8)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet(f"color: {theme.BAD}; background: transparent;")
        self.problems.hide()
        lay.addWidget(self.problems)

        # cards -------------------------------------------------------------
        cards_box = QGroupBox("Recognized cards (click a card to correct it)")
        cl = QGridLayout(cards_box)
        cl.addWidget(self._caption("Hero"), 0, 0)
        self.hero_buttons = [CardButton(), CardButton()]
        hero_row = QHBoxLayout()
        for i, b in enumerate(self.hero_buttons):
            b.clicked.connect(lambda _=False, i=i: self._edit_card("hero", i))
            hero_row.addWidget(b)
        hero_row.addStretch(1)
        cl.addLayout(hero_row, 0, 1)
        cl.addWidget(self._caption("Board"), 1, 0)
        self.board_row = QHBoxLayout()
        cl.addLayout(self.board_row, 1, 1)
        lay.addWidget(cards_box)

        # hand information ----------------------------------------------------
        info = QGroupBox("Extracted information")
        g = QGridLayout(info)
        g.setColumnStretch(1, 1)
        self.badges = {}
        r = 0
        self.street_combo = QComboBox()
        self.street_combo.addItems(["UNKNOWN", "Preflop", "Flop", "Turn", "River"])
        self.street_combo.currentIndexChanged.connect(self._street_changed)
        r = self._row(g, r, "Street", self.street_combo, "street")
        self.pot_edit = AmountEdit()
        self.pot_edit.valueEdited.connect(self._pot_changed)
        self.pot_incl = QCheckBox("includes bets in front of players")
        self.pot_incl.toggled.connect(self._pot_incl_changed)
        r = self._row(g, r, "Pot", labeled_row(self.pot_edit, self.pot_incl, "stretch"), "pot")
        self.sb_edit, self.bb_edit = AmountEdit(placeholder="SB"), AmountEdit(placeholder="BB")
        for e in (self.sb_edit, self.bb_edit):
            e.valueEdited.connect(self._blinds_changed)
        r = self._row(g, r, "Blinds", labeled_row(self.sb_edit, QLabel("/"), self.bb_edit, "stretch"), "blinds")
        self.to_call_edit = AmountEdit()
        self.to_call_edit.valueEdited.connect(self._to_call_changed)
        r = self._row(g, r, "To call", self.to_call_edit, "to_call")
        self.to_act_combo = QComboBox()
        self.to_act_combo.addItems(["UNKNOWN", "Yes", "No"])
        self.to_act_combo.currentIndexChanged.connect(self._to_act_changed)
        r = self._row(g, r, "Hero to act", self.to_act_combo, "hero_to_act")
        self.actions_edit = QLineEdit()
        self.actions_edit.setPlaceholderText("UNKNOWN   e.g. Fold, Call 60, Raise to 240")
        self.actions_edit.editingFinished.connect(self._actions_changed)
        r = self._row(g, r, "Available actions", self.actions_edit, "actions")
        lay.addWidget(info)

        # players -------------------------------------------------------------
        players = QGroupBox("Players (hero first, then clockwise)")
        pl = QVBoxLayout(players)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Position", "Stack", "Bet", "Last action", "In hand"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(78)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(200)
        pl.addWidget(self.table)
        add = QPushButton("Add opponent")
        add.clicked.connect(self._add_opponent)
        rem = QPushButton("Remove selected")
        rem.clicked.connect(self._remove_opponent)
        hint = QLabel("Names are only shown here to help you match seats; they are never sent.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        pl.addWidget(labeled_row(add, rem, "stretch"))
        pl.addWidget(hint)
        lay.addWidget(players)

        # local maths ------------------------------------------------------
        math = QGroupBox("Local math (estimates, not solver output)")
        ml = QGridLayout(math)
        self.range_combo = QComboBox()
        for key, (name, frac) in PRESETS.items():
            self.range_combo.addItem(f"{name} ({int(frac * 100)}%)" if frac < 1 else name, key)
        self.range_combo.addItem("Custom range...", "custom")
        self.range_combo.currentIndexChanged.connect(self._range_changed)
        self.custom_range = QLineEdit()
        self.custom_range.setPlaceholderText("e.g. 22+, A2s+, KTs+, QJs, AJo+, KQo")
        self.custom_range.editingFinished.connect(self._range_changed)
        self.custom_range.setEnabled(False)
        ml.addWidget(QLabel("Opponent range"), 0, 0)
        ml.addWidget(self.range_combo, 0, 1)
        ml.addWidget(self.custom_range, 1, 1)
        self.math_summary = QLabel("Capture a table to see pot odds and equity.")
        self.math_summary.setWordWrap(True)
        self.math_summary.setObjectName("muted")
        ml.addWidget(self.math_summary, 2, 0, 1, 2)
        lay.addWidget(math)
        lay.addStretch(1)
        self.set_state(GameState())

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _caption(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("heading")
        return lab

    def _row(self, grid: QGridLayout, r: int, label: str, widget: QWidget, key: str) -> int:
        grid.addWidget(QLabel(label), r, 0)
        grid.addWidget(widget, r, 1)
        badge = ConfidenceBadge()
        self.badges[key] = badge
        grid.addWidget(badge, r, 2)
        return r + 1

    def range_key(self) -> str:
        return self.range_combo.currentData()

    def set_range(self, key: str, custom: str = "") -> None:
        i = self.range_combo.findData(key)
        self.range_combo.blockSignals(True)
        self.range_combo.setCurrentIndex(max(0, i))
        self.range_combo.blockSignals(False)
        self.custom_range.setText(custom)
        self.custom_range.setEnabled(key == "custom")

    def set_math_summary(self, text: str, level: str = "info") -> None:
        color = {"info": theme.MUTED, "warn": theme.WARN, "error": theme.BAD}.get(level, theme.MUTED)
        self.math_summary.setStyleSheet(f"color: {color}; background: transparent;")
        self.math_summary.setText(text)

    # --------------------------------------------------------------- state
    def set_state(self, state: GameState) -> None:
        self.state = state
        self._building = True
        try:
            self._refresh_cards()
            self._refresh_info()
            self._refresh_players()
            self._refresh_problems()
        finally:
            self._building = False

    def _edited(self) -> None:
        if self._building:
            return
        self._refresh_problems()
        self.stateEdited.emit()

    def _refresh_problems(self) -> None:
        problems = self.state.validate()
        self.problems.setVisible(bool(problems))
        self.problems.setText("Check: " + " ".join(problems))

    def _refresh_cards(self) -> None:
        for f, b in zip(self.state.hero_cards, self.hero_buttons):
            b.set_field(f, self.threshold)
        while self.board_row.count():
            item = self.board_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, f in enumerate(self.state.board):
            b = CardButton()
            b.set_field(f, self.threshold)
            b.clicked.connect(lambda _=False, i=i: self._edit_card("board", i))
            self.board_row.addWidget(b)
        if len(self.state.board) < 5:
            add = QPushButton("+")
            add.setFixedSize(40, 70)
            add.setToolTip("Add a board card")
            add.clicked.connect(lambda: self._edit_card("board", len(self.state.board)))
            self.board_row.addWidget(add, 0, Qt.AlignmentFlag.AlignTop)
        self.board_row.addStretch(1)

    def _refresh_info(self) -> None:
        st, T = self.state, self.threshold
        self.street_combo.setCurrentIndex(0 if not st.street.known else STREETS.index(st.street.value) + 1)
        self.badges["street"].set_field(st.street, T)
        self.pot_edit.set_value(st.pot.value if st.pot.known else None)
        self.pot_edit.setToolTip(self.badges["street"].toolTip())
        self.pot_incl.blockSignals(True)
        self.pot_incl.setChecked(st.pot_includes_bets)
        self.pot_incl.blockSignals(False)
        self.badges["pot"].set_field(st.pot, T)
        sb, bb = st.blinds.value if st.blinds.known else (None, None)
        self.sb_edit.set_value(sb)
        self.bb_edit.set_value(bb)
        self.badges["blinds"].set_field(st.blinds, T)
        self.to_call_edit.set_value(st.to_call.value if st.to_call.known else None)
        self.badges["to_call"].set_field(st.to_call, T)
        self.to_act_combo.setCurrentIndex(0 if not st.hero_to_act.known else (1 if st.hero_to_act.value else 2))
        self.badges["hero_to_act"].set_field(st.hero_to_act, T)
        acts = st.available_actions
        self.actions_edit.setText(describe_actions(acts.value) if acts.known and acts.value else "")
        self.actions_edit.setStyleSheet("")
        self.badges["actions"].set_field(acts, T)

    def _refresh_players(self) -> None:
        T = self.threshold
        players = self.state.players
        if not any(p.is_hero for p in players):
            players.insert(0, Player(seat=0, is_hero=True))
        self.table.setRowCount(len(players))
        n = 0
        for row, p in enumerate(players):
            if p.is_hero:
                header = "Hero"
            else:
                n += 1
                header = f"Opp {n}" + (f"  {p.name}" if p.name else "")
            self.table.setVerticalHeaderItem(row, self._header_item(header))
            pos = QComboBox()
            pos.addItem("UNKNOWN", None)
            for code in POSITION_CODES:
                pos.addItem(code, code)
                pos.setItemData(pos.count() - 1, position_label(code), Qt.ItemDataRole.ToolTipRole)
            pos.setCurrentIndex(max(0, pos.findData(p.position.value)) if p.position.known else 0)
            pos.setStyleSheet(f"QComboBox {{ {_style_for(p.position, T)} }}")
            pos.setToolTip(self._tip(p.position))
            pos.currentIndexChanged.connect(lambda _=0, p=p, w=pos: self._set(p, "position", w.currentData()))
            self.table.setCellWidget(row, 0, pos)
            for col, attr in ((1, "stack"), (2, "bet")):
                e = AmountEdit()
                e.setMaximumWidth(10000)
                f = getattr(p, attr)
                e.set_value(f.value if f.known else None)
                e.setStyleSheet(f"QLineEdit {{ {_style_for(f, T)} }}")
                e.setToolTip(self._tip(f))
                e.valueEdited.connect(lambda p=p, a=attr, w=e: self._set(p, a, w.value()))
                self.table.setCellWidget(row, col, e)
            act = QLineEdit(p.last_action.value.describe() if p.last_action.known else "")
            act.setPlaceholderText("UNKNOWN")
            act.setStyleSheet(f"QLineEdit {{ {_style_for(p.last_action, T)} }}")
            act.setToolTip(self._tip(p.last_action))
            act.editingFinished.connect(lambda p=p, w=act: self._set_action(p, w))
            self.table.setCellWidget(row, 3, act)
            ih = QComboBox()
            ih.addItems(["UNKNOWN", "Yes", "Folded"])
            ih.setCurrentIndex(0 if not p.in_hand.known else (1 if p.in_hand.value else 2))
            ih.setStyleSheet(f"QComboBox {{ {_style_for(p.in_hand, T)} }}")
            ih.setToolTip(self._tip(p.in_hand))
            ih.currentIndexChanged.connect(lambda i, p=p: self._set(p, "in_hand", None if i == 0 else i == 1))
            self.table.setCellWidget(row, 4, ih)

    @staticmethod
    def _header_item(text: str):
        from PySide6.QtWidgets import QTableWidgetItem

        return QTableWidgetItem(text)

    @staticmethod
    def _tip(field: Field) -> str:
        from .widgets import badge_tooltip

        return badge_tooltip(field)

    # -------------------------------------------------------------- edits
    def _set(self, player: Player, attr: str, value) -> None:
        if self._building:
            return
        setattr(player, attr, Field.manual(value) if value is not None else UNKNOWN_FIELD())
        self._edited()

    def _set_action(self, player: Player, widget: QLineEdit) -> None:
        text = widget.text().strip()
        if not text:
            new = UNKNOWN_FIELD()
        else:
            a = Action.parse(text)
            if a is None:
                widget.setStyleSheet(f"QLineEdit {{ border: 1px solid {theme.BAD}; }}")
                widget.setToolTip("Use Fold, Check, Call 60, Bet 60, Raise to 240 or All-in 950")
                return
            new = Field.manual(a)
        if new.value == player.last_action.value and player.last_action.source == "manual":
            return
        player.last_action = new
        widget.setStyleSheet(f"QLineEdit {{ {_style_for(new, self.threshold)} }}")
        self._edited()

    def _street_changed(self, index: int) -> None:
        if self._building:
            return
        self.state.street = Field.manual(STREETS[index - 1]) if index else UNKNOWN_FIELD()
        self.badges["street"].set_field(self.state.street, self.threshold)
        self._edited()

    def _pot_changed(self) -> None:
        v = self.pot_edit.value()
        self.state.pot = Field.manual(v) if v is not None else UNKNOWN_FIELD()
        self.badges["pot"].set_field(self.state.pot, self.threshold)
        self._edited()

    def _pot_incl_changed(self, checked: bool) -> None:
        self.state.pot_includes_bets = checked
        self._edited()

    def _blinds_changed(self) -> None:
        sb, bb = self.sb_edit.value(), self.bb_edit.value()
        self.state.blinds = Field.manual((sb, bb)) if sb is not None and bb is not None else UNKNOWN_FIELD()
        self.badges["blinds"].set_field(self.state.blinds, self.threshold)
        self._edited()

    def _to_call_changed(self) -> None:
        v = self.to_call_edit.value()
        self.state.to_call = Field.manual(v) if v is not None else UNKNOWN_FIELD()
        self.badges["to_call"].set_field(self.state.to_call, self.threshold)
        self._edited()

    def _to_act_changed(self, index: int) -> None:
        if self._building:
            return
        self.state.hero_to_act = UNKNOWN_FIELD() if index == 0 else Field.manual(index == 1)
        self.badges["hero_to_act"].set_field(self.state.hero_to_act, self.threshold)
        self._edited()

    def _actions_changed(self) -> None:
        text = self.actions_edit.text().strip()
        try:
            actions = Action.parse_list(text) if text else None
        except ValueError as exc:
            self.actions_edit.setStyleSheet(f"QLineEdit {{ border: 1px solid {theme.BAD}; }}")
            self.actions_edit.setToolTip(str(exc))
            return
        self.actions_edit.setStyleSheet("")
        new = Field.manual(actions) if actions else UNKNOWN_FIELD()
        if new.value == self.state.available_actions.value:
            return
        self.state.available_actions = new
        self.badges["actions"].set_field(new, self.threshold)
        self._edited()

    def _range_changed(self, *_):
        self.custom_range.setEnabled(self.range_key() == "custom")
        if not self._building:
            self.rangeChanged.emit()

    def _add_opponent(self) -> None:
        self.state.players.append(Player(seat=len(self.state.players)))
        self._building = True
        self._refresh_players()
        self._building = False
        self._edited()

    def _remove_opponent(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        changed = False
        for r in rows:
            if 0 <= r < len(self.state.players) and not self.state.players[r].is_hero:
                del self.state.players[r]
                changed = True
        if changed:
            self._building = True
            self._refresh_players()
            self._building = False
            self._edited()

    def _edit_card(self, kind: str, index: int) -> None:
        fields = self.state.hero_cards if kind == "hero" else self.state.board
        current = fields[index] if index < len(fields) else Field()
        used = [f.value for f in self.state.hero_cards + self.state.board if f.known]
        title = f"Hero card {index + 1}" if kind == "hero" else f"Board card {index + 1}"
        dlg = CardPicker(self, title, current.value, current.guess if isinstance(current.guess, str) else None, used,
                         allow_remove=kind == "board" and index < len(fields))
        if not dlg.exec() or dlg.choice is None:
            return
        self.apply_card_choice(kind, index, dlg.choice)

    def apply_card_choice(self, kind: str, index: int, choice: str) -> None:
        """Also used by tests: choice is a card code, CardPicker.UNKNOWN or CardPicker.REMOVE."""
        fields = self.state.hero_cards if kind == "hero" else self.state.board
        if choice == CardPicker.REMOVE:
            if index < len(fields):
                del fields[index]
        else:
            new = UNKNOWN_FIELD() if choice == CardPicker.UNKNOWN else Field.manual(choice)
            if index < len(fields):
                fields[index] = new
            else:
                fields.append(new)
            if choice not in (CardPicker.UNKNOWN, CardPicker.REMOVE):
                self.cardCorrected.emit(kind, index, choice)
        if kind == "board" and self.state.street.source != "manual":
            street = self.state.street_from_board()
            self.state.street = Field.derived(street, 1.0) if street else Field()
        self._building = True
        self._refresh_cards()
        self._refresh_info()
        self._building = False
        self._edited()
