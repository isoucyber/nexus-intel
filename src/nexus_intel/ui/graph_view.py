"""Grafo interativo nativo (QGraphicsView), seção 6.8.

Layout de força (Fruchterman-Reingold) vetorizado com NumPy. Limite de nós
visíveis, modo Foco (vizinhança da entidade), estilo de linha por status
epistêmico, arrastar nós, zoom, menu de contexto e exportação PNG.
"""

from __future__ import annotations

from shiboken6 import isValid

import math
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
    QSpinBox,
    QWidget,
)

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.ui.common import Page, button, guarded, hbox, label
from nexus_intel.ui.dialogs import RelationDialog
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import on_theme, paint_avatar

STATUS_PEN = {
    "verified": Qt.PenStyle.SolidLine,
    "reported": Qt.PenStyle.DashLine,
    "unverified": Qt.PenStyle.DashDotLine,
    "hypothesis": Qt.PenStyle.DotLine,
    "conflicting": Qt.PenStyle.SolidLine,
    "refuted": Qt.PenStyle.DotLine,
}


def force_layout(n: int, edges: list[tuple[int, int]], iterations: int = 250, seed: int = 7) -> np.ndarray:
    if n == 0:
        return np.zeros((0, 2))
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1, 1, (n, 2)) * math.sqrt(n) * 60
    if n == 1:
        return np.zeros((1, 2))
    k = 90.0
    temp = math.sqrt(n) * 40
    gravity = 0.08 * math.sqrt(n)
    e = np.array(edges, dtype=int).reshape(-1, 2)
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2) + 1e-6
        np.fill_diagonal(dist, np.inf)
        disp = (delta / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        if len(e):
            d = pos[e[:, 0]] - pos[e[:, 1]]
            dl = np.linalg.norm(d, axis=1)[:, None] + 1e-6
            f = d / dl * (dl * dl / k)
            np.add.at(disp, e[:, 0], -f)
            np.add.at(disp, e[:, 1], f)
        disp -= pos * gravity  # componentes desconexas ficam próximas, não fogem da tela
        length = np.linalg.norm(disp, axis=1)[:, None] + 1e-6
        pos += disp / length * np.minimum(length, temp)
        temp *= 0.97
    return pos - pos.mean(axis=0)


class NodeItem(QGraphicsObject):
    def __init__(self, data: dict[str, Any], view: GraphView, radius: float) -> None:
        super().__init__()
        self.data_ = data
        self.view = view
        self.radius = radius
        self.edges: list[EdgeItem] = []
        t = tokens.current()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{data['display_name']}\n{data['type_label']}")
        self.setZValue(2)
        text = data["display_name"]
        self.text = QGraphicsSimpleTextItem(text if len(text) <= 28 else text[:26] + "…", self)
        self.text.setBrush(assets.qcolor(t.graph_label))
        f = QFont(assets.font_family("ui"))
        f.setPixelSize(max(10, t.font_px("xs") - 1))
        self.text.setFont(f)
        br = self.text.boundingRect()
        self.text.setPos(-br.width() / 2, radius + 3)

    def boundingRect(self) -> QRectF:
        r = self.radius + 4
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, p: QPainter, _opt: Any, _w: Any = None) -> None:
        t = tokens.current()
        ring = None
        if self.isSelected():
            ring = t.focus
        elif self.data_["id"] == self.view.center_id:
            ring = t.accent
        r = self.radius
        paint_avatar(p, QRectF(-r, -r, 2 * r, 2 * r), self.data_.get("type_key") or "other",
                     ring or t.type_color(self.data_.get("type_key")))

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for e in self.edges:
                e.adjust()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.view.node_activated.emit(self.data_["id"])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: Any) -> None:
        self.view.node_menu(self, event.screenPos())


class EdgeItem(QGraphicsPathItem):
    def __init__(self, data: dict[str, Any], a: NodeItem, b: NodeItem, base: str) -> None:
        super().__init__()
        self.data_, self.a, self.b = data, a, b
        status = data["epistemic_status"]
        t = tokens.current()
        color = assets.qcolor(base)
        if status in ("conflicting", "verified"):
            color = assets.qcolor(t.status_color(status), 0.85)
        pen = QPen(color, 2.2 if status == "verified" else 1.6, STATUS_PEN.get(status, Qt.PenStyle.SolidLine))
        self.setPen(pen)
        self.setZValue(1)
        self.setToolTip(f"{a.data_['display_name']} — {data['label']} → {b.data_['display_name']}\n"
                        f"status: {status}")
        a.edges.append(self)
        b.edges.append(self)
        self.adjust()

    def adjust(self) -> None:
        p1, p2 = self.a.pos(), self.b.pos()
        line = p2 - p1
        length = math.hypot(line.x(), line.y()) or 1.0
        ux, uy = line.x() / length, line.y() / length
        start = QPointF(p1.x() + ux * self.a.radius, p1.y() + uy * self.a.radius)
        end = QPointF(p2.x() - ux * self.b.radius, p2.y() - uy * self.b.radius)
        path = QPainterPath(start)
        path.lineTo(end)
        if self.data_["directed"]:
            size = 8.0
            left = QPointF(end.x() - ux * size - uy * size * 0.5, end.y() - uy * size + ux * size * 0.5)
            right = QPointF(end.x() - ux * size + uy * size * 0.5, end.y() - uy * size - ux * size * 0.5)
            path.moveTo(left)
            path.lineTo(end)
            path.lineTo(right)
        self.setPath(path)


class GraphView(QGraphicsView):
    node_activated = Signal(str)
    node_selected = Signal(str)

    def __init__(self, page: GraphPage) -> None:
        super().__init__()
        self.page = page
        self.center_id: str | None = None
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.scene().selectionChanged.connect(self._sel)

    def _sel(self) -> None:
        items = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        if items:
            self.node_selected.emit(items[0].data_["id"])

    def wheelEvent(self, event: Any) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.05 < scale < 6:
            self.scale(factor, factor)

    def mousePressEvent(self, event: Any) -> None:
        item = self.itemAt(event.position().toPoint())
        node = item if isinstance(item, NodeItem) else (item.parentItem() if item else None)
        self.setDragMode(QGraphicsView.DragMode.NoDrag if isinstance(node, NodeItem)
                         else QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def node_menu(self, node: NodeItem, screen_pos: Any) -> None:
        eid = node.data_["id"]
        m = QMenu(self)
        m.addAction("Abrir entidade", lambda: self.node_activated.emit(eid))
        m.addAction("Focar aqui (vizinhança)", lambda: self.page.focus(eid))
        m.addAction("Criar relação a partir daqui…", lambda: self.page.new_relation(eid))
        m.addAction("Ocultar do grafo", lambda: self.page.hide_node(eid))
        m.exec(screen_pos)

    def fit(self) -> None:
        rect = self.scene().itemsBoundingRect().adjusted(-60, -60, 60, 60)
        if not rect.isEmpty():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 1.6:
                self.resetTransform()
                self.scale(1.6, 1.6)
                self.centerOn(rect.center())


class GraphPage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.hidden: set[str] = set()
        self.view = GraphView(self)
        self.view.setBackgroundBrush(assets.qcolor(tokens.current().graph_bg))
        on_theme(self, self._retheme)
        self.view.node_activated.connect(self.open_entity.emit)
        self.view.node_selected.connect(self._selected)

        self.type_filter = QComboBox()
        self.type_filter.addItem("Todos os tipos", None)
        for t in store.entity_types():
            self.type_filter.addItem(t["label"], t["id"])
        self.only_verified = QCheckBox("Só relações verificadas")
        self.limit = QSpinBox()
        self.limit.setRange(10, 1000)
        self.limit.setValue(300)
        self.limit.setPrefix("até ")
        self.limit.setSuffix(" nós")
        self.depth = QSpinBox()
        self.depth.setRange(1, 4)
        self.depth.setValue(2)
        self.depth.setPrefix("foco: ")
        self.depth.setSuffix(" saltos")
        self.info = label("", "Muted")
        self.sel_info = label("", "Muted")
        for w in (self.type_filter,):
            w.currentIndexChanged.connect(lambda _: self.reload())
        self.only_verified.toggled.connect(lambda _: self.reload())
        self.limit.editingFinished.connect(self.reload)
        self.depth.editingFinished.connect(self.reload)

        self.layout_.addWidget(hbox(
            label("Grafo", "H1"), None, self.type_filter, self.only_verified, self.limit, self.depth,
            button("Ver tudo", self.show_all), button("Reorganizar", self.reload),
            button("Exportar PNG", self.export_png)))
        self.layout_.addWidget(hbox(self.info, None, self.sel_info))
        self.layout_.addWidget(self.view, 1)
        self.layout_.addWidget(label(
            "Duplo clique abre a entidade · botão direito: focar, criar relação, ocultar · roda do mouse: zoom · "
            "arraste o fundo para mover. Linha contínua = verificada; tracejada = relatada; "
            "pontilhada = hipótese; vermelha = conflito.", "Muted", wrap=True))

    def _retheme(self, t: tokens.Tokens) -> None:
        self.view.setBackgroundBrush(assets.qcolor(t.graph_bg))
        if self.view.scene().items():
            self.reload(keep_positions=True)

    def _selected(self, eid: str) -> None:
        e = guarded(self, lambda: self.store.get_entity(eid))
        if e:
            self.sel_info.setText(f"Selecionado: {e['display_name']} ({e['type_label']})")

    def focus(self, eid: str | None) -> None:
        self.view.center_id = eid
        self.hidden.clear()
        self.reload()

    def show_all(self) -> None:
        self.focus(None)

    def hide_node(self, eid: str) -> None:
        self.hidden.add(eid)
        self.reload(keep_positions=True)

    def new_relation(self, eid: str) -> None:
        if RelationDialog(self.store, eid, self).exec():
            self.reload(keep_positions=True)

    def reload(self, keep_positions: bool = False) -> None:
        if not isValid(self) or not isValid(self.view):
            return  # sinal emitido durante a destruição da tela
        old = {}
        if keep_positions:
            old = {i.data_["id"]: i.pos() for i in self.view.scene().items() if isinstance(i, NodeItem)}
        tid = self.type_filter.currentData()
        data = guarded(self, lambda: self.store.graph_data(
            center_id=self.view.center_id, depth=self.depth.value(), limit=self.limit.value(),
            type_ids=[tid] if tid else None,
            statuses=["verified"] if self.only_verified.isChecked() else None))
        if data is None:
            return
        scene = self.view.scene()
        scene.clear()
        nodes = [n for n in data["nodes"] if n["id"] not in self.hidden]
        index = {n["id"]: i for i, n in enumerate(nodes)}
        edges = [e for e in data["edges"] if e["source_id"] in index and e["target_id"] in index]
        if not nodes:
            self.info.setText("Nenhuma entidade para mostrar. Cadastre entidades e relações na Central.")
            return
        iters = max(60, min(300, 30000 // max(1, len(nodes))))
        pos = force_layout(len(nodes), [(index[e["source_id"]], index[e["target_id"]]) for e in edges], iters)
        degree = {n["id"]: 0 for n in nodes}
        for e in edges:
            degree[e["source_id"]] += 1
            degree[e["target_id"]] += 1
        items: dict[str, NodeItem] = {}
        for i, n in enumerate(nodes):
            r = 9 + min(14, degree[n["id"]] * 1.5) + n["importance"]
            it = NodeItem(n, self.view, r)
            p = old.get(n["id"])
            it.setPos(p if p is not None else QPointF(float(pos[i, 0]), float(pos[i, 1])))
            scene.addItem(it)
            items[n["id"]] = it
        for e in edges:
            scene.addItem(EdgeItem(e, items[e["source_id"]], items[e["target_id"]], tokens.current().graph_edge))
        mode = "Foco" if self.view.center_id else "Visão geral"
        trunc = f" (limite atingido: mostrando os {len(nodes)} mais conectados)" if data["truncated"] else ""
        self.info.setText(f"{mode}: {len(nodes)} de {data['total_entities']} entidades · "
                          f"{len(edges)} relações{trunc}")
        if not keep_positions:
            self.view.fit()

    def export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar grafo", "grafo.png", "Imagem PNG (*.png)")
        if not path:
            return
        scene = self.view.scene()
        rect = scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        img = QImage(int(rect.width() * 2), int(rect.height() * 2), QImage.Format.Format_ARGB32)
        img.fill(assets.qcolor(tokens.current().graph_bg))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(p, QRectF(img.rect()), rect)
        p.end()
        img.save(path)


__all__ = ["GraphPage", "QWidget", "force_layout"]
