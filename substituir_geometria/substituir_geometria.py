from collections import defaultdict
import os
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsCoordinateTransform, QgsExpression, QgsFeatureRequest, QgsGeometry,
    QgsMapLayerProxyModel, QgsProject, QgsVectorLayer,
)
from qgis.gui import QgsMapCanvas, QgsMapLayerComboBox, QgsRubberBand


class SubstituirGeometriaPlugin:
    """Substitui geometrias em lote, com prévia no mapa e comparação antes/depois."""

    def __init__(self, iface):
        self.iface = iface
        self.action = self.dialog = self.toolbar = None
        self.preview_bands, self.operations, self.issues = [], [], []
        self.overview_bands = {"old": None, "new": None}

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icone.png")
        self.action = QAction(QIcon(icon_path), "Substituir geometria", self.iface.mainWindow())
        self.action.setToolTip("Substituir geometria")
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToMenu("&Substituir geometria", self.action)
        self.toolbar = self.iface.addToolBar("Substituir geometria")
        self.toolbar.setObjectName("SubstituirGeometriaToolbar")
        self.toolbar.setMovable(True)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.toolbar.addAction(self.action)

    def unload(self):
        self.clear_preview()
        if self.action:
            self.iface.removePluginMenu("&Substituir geometria", self.action)
        if self.toolbar:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

    def show_dialog(self):
        self.clear_preview()
        self.operations, self.issues = [], []
        self.dialog = QDialog(self.iface.mainWindow())
        self.dialog.setWindowTitle("Substituir geometria")
        self.dialog.setMinimumSize(1060, 700)
        root_layout = QHBoxLayout(self.dialog)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        mode_form = QFormLayout()
        self.operation_mode = QComboBox()
        self.operation_mode.addItem("Uma geometria para vários identificadores", "single_geometry")
        self.operation_mode.addItem("Várias geometrias por identificador", "matched_geometries")
        self.operation_mode.currentIndexChanged.connect(self.update_mode_controls)
        mode_form.addRow("Modo de operação:", self.operation_mode)
        left_layout.addLayout(mode_form)

        source_form = QFormLayout()
        self.source_layer = QgsMapLayerComboBox()
        self.source_layer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.source_layer.layerChanged.connect(self.populate_source_fields)
        source_form.addRow("Camada com geometrias novas:", self.source_layer)
        self.source_field = QComboBox()
        self.source_field_label = QLabel("Campo identificador da origem:")
        source_form.addRow(self.source_field_label, self.source_field)
        left_layout.addLayout(source_form)

        self.identifiers_label = QLabel("RIPs/identificadores a processar (um por linha, vírgula ou ponto e vírgula):")
        left_layout.addWidget(self.identifiers_label)
        self.identifiers = QPlainTextEdit()
        self.identifiers.setPlaceholderText("Em branco: processa todas as feições da camada de origem")
        self.identifiers.setMaximumHeight(70)
        left_layout.addWidget(self.identifiers)

        target_form = QHBoxLayout()
        self.target_layer = QgsMapLayerComboBox()
        self.target_layer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        add_button = QPushButton("Adicionar camada-alvo")
        add_button.clicked.connect(self.add_target_layer)
        target_form.addWidget(QLabel("Camada-alvo:"))
        target_form.addWidget(self.target_layer)
        target_form.addWidget(add_button)
        left_layout.addLayout(target_form)

        self.targets_table = QTableWidget(0, 4)
        self.targets_table.setHorizontalHeaderLabels(["Camada-alvo", "Campo identificador", "Resultado da prévia", "Ação"])
        self.targets_table.horizontalHeader().setStretchLastSection(True)
        self.targets_table.setMaximumHeight(145)
        left_layout.addWidget(self.targets_table)
        left_layout.addWidget(QLabel("Substituições válidas (clique em uma linha para comparar):"))
        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Camada", "Identificador", "Situação"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.itemSelectionChanged.connect(self.show_selected_overview)
        left_layout.addWidget(self.results_table)

        self.info = QLabel()
        self.info.setWordWrap(True)
        left_layout.addWidget(self.info)
        buttons = QHBoxLayout()
        preview_button = QPushButton("Atualizar prévia")
        preview_button.clicked.connect(self.update_preview)
        self.apply_button = QPushButton("Aplicar substituições válidas")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_changes)
        buttons.addWidget(preview_button)
        buttons.addWidget(self.apply_button)
        left_layout.addLayout(buttons)
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.close_dialog)
        left_layout.addWidget(close_buttons)

        right = self.create_overview_panel()
        root_layout.addWidget(left, 3)
        root_layout.addWidget(right, 2)
        self.populate_source_fields(self.source_layer.currentLayer())
        self.update_mode_controls()
        self.dialog.show()

    def create_overview_panel(self):
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        title = QLabel("Comparação da alteração selecionada")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        self.overview_info = QLabel("Gere a prévia e selecione uma substituição válida na lista.")
        self.overview_info.setWordWrap(True)
        layout.addWidget(self.overview_info)

        layout.addWidget(self.overview_label("Original", QColor(210, 0, 0)))
        self.old_canvas = self.create_canvas()
        layout.addWidget(self.old_canvas, 1)
        layout.addWidget(self.overview_label("Nova geometria", QColor(0, 150, 0)))
        self.new_canvas = self.create_canvas()
        layout.addWidget(self.new_canvas, 1)

        zoom_button = QPushButton("Ampliar no mapa principal")
        zoom_button.clicked.connect(self.zoom_selected_on_main_canvas)
        layout.addWidget(zoom_button)
        return panel

    @staticmethod
    def overview_label(text, color):
        label = QLabel(text)
        label.setStyleSheet(f"font-weight: bold; color: {color.name()};")
        return label

    @staticmethod
    def create_canvas():
        canvas = QgsMapCanvas()
        canvas.setCanvasColor(QColor(250, 250, 250))
        canvas.setMinimumHeight(190)
        canvas.setLayers([])
        return canvas

    def populate_source_fields(self, layer):
        self.source_field.clear()
        if isinstance(layer, QgsVectorLayer):
            self.source_field.addItems([field.name() for field in layer.fields()])
            rip_index = self.source_field.findText("rip", Qt.MatchFixedString)
            if rip_index >= 0:
                self.source_field.setCurrentIndex(rip_index)

    def update_mode_controls(self):
        """Exibe somente os campos pertinentes ao modo de associação escolhido."""
        is_matched = self.operation_mode.currentData() == "matched_geometries"
        self.source_field_label.setVisible(is_matched)
        self.source_field.setVisible(is_matched)
        if is_matched:
            self.identifiers_label.setText(
                "RIPs/identificadores a processar (opcional; em branco processa todas as geometrias):"
            )
            self.identifiers.setPlaceholderText("Em branco: processa todas as feições da camada de origem")
            self.info.setText(
                "Cada geometria da origem será associada pelo campo identificador escolhido. "
                "Feições selecionadas na origem têm prioridade; sem seleção, todas são consideradas."
            )
        else:
            self.identifiers_label.setText(
                "RIPs/identificadores que receberão a mesma geometria (obrigatório):"
            )
            self.identifiers.setPlaceholderText("Exemplo: 4895 00014.500-8")
            self.info.setText(
                "Selecione uma única geometria na camada de origem. Ela será aplicada aos identificadores informados, "
                "usando o campo escolhido em cada camada-alvo. Sem seleção, será usada a primeira feição da origem."
            )

    def add_target_layer(self):
        layer = self.target_layer.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            return
        for row in range(self.targets_table.rowCount()):
            combo = self.targets_table.cellWidget(row, 1)
            if combo.property("layer_id") == layer.id():
                self.info.setText("Essa camada já está na lista de camadas-alvo.")
                return
        row = self.targets_table.rowCount()
        self.targets_table.insertRow(row)
        self.targets_table.setItem(row, 0, QTableWidgetItem(layer.name()))
        combo = QComboBox()
        combo.setProperty("layer_id", layer.id())
        combo.addItems([field.name() for field in layer.fields()])
        rip_index = combo.findText("rip", Qt.MatchFixedString)
        if rip_index >= 0:
            combo.setCurrentIndex(rip_index)
        self.targets_table.setCellWidget(row, 1, combo)
        self.targets_table.setItem(row, 2, QTableWidgetItem("Aguardando prévia"))
        remove_button = QPushButton("Remover")
        remove_button.clicked.connect(lambda checked=False, layer_id=layer.id(): self.remove_target_layer_by_id(layer_id))
        self.targets_table.setCellWidget(row, 3, remove_button)

    def remove_target_layer(self):
        row = self.targets_table.currentRow()
        if row >= 0:
            self.targets_table.removeRow(row)

    def remove_target_layer_by_id(self, layer_id):
        """Remove a camada pelo botão da própria linha, mesmo sem seleção na tabela."""
        for row in range(self.targets_table.rowCount()):
            combo = self.targets_table.cellWidget(row, 1)
            if combo and combo.property("layer_id") == layer_id:
                self.targets_table.removeRow(row)
                self.info.setText("Camada-alvo removida da configuração.")
                return

    @staticmethod
    def key(value):
        return str(value).strip() if value is not None else ""

    def requested_identifiers(self):
        return {item.strip() for item in re.split(r"[\n,;]+", self.identifiers.toPlainText()) if item.strip()}

    def source_geometries_by_key(self):
        layer = self.source_layer.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            raise ValueError("Escolha uma camada de origem válida.")
        requested = self.requested_identifiers()
        if self.operation_mode.currentData() == "single_geometry":
            if not requested:
                raise ValueError("Informe ao menos um RIP/identificador para receber a geometria.")
            selected = layer.selectedFeatures()
            if len(selected) > 1:
                raise ValueError("Selecione somente uma geometria na camada de origem.")
            feature = selected[0] if selected else next(layer.getFeatures(), None)
            if feature is None or feature.geometry().isNull() or feature.geometry().isEmpty():
                raise ValueError("A camada de origem não possui uma geometria válida.")
            geometry = QgsGeometry(feature.geometry())
            return layer, {key: [geometry] for key in requested}, requested

        field_name = self.source_field.currentText()
        if not field_name:
            raise ValueError("Escolha o campo identificador da camada de origem.")
        grouped = defaultdict(list)
        for feature in (layer.selectedFeatures() or list(layer.getFeatures())):
            value = self.key(feature[field_name])
            if value and (not requested or value in requested) and not feature.geometry().isNull() and not feature.geometry().isEmpty():
                grouped[value].append(QgsGeometry(feature.geometry()))
        return layer, grouped, requested

    def target_rows(self):
        project_layers = QgsProject.instance().mapLayers()
        rows = []
        for row in range(self.targets_table.rowCount()):
            combo = self.targets_table.cellWidget(row, 1)
            layer = project_layers.get(combo.property("layer_id"))
            if isinstance(layer, QgsVectorLayer) and combo.currentText():
                rows.append((row, layer, combo.currentText()))
        return rows

    def geometry_for_target(self, geometry, source_layer, target_layer):
        result = QgsGeometry(geometry)
        if source_layer.crs() != target_layer.crs():
            transform = QgsCoordinateTransform(source_layer.crs(), target_layer.crs(), QgsProject.instance())
            if result.transform(transform) != 0:
                raise ValueError("Falha ao reprojetar a geometria para " + target_layer.name())
        return result

    def update_preview(self):
        self.clear_preview()
        self.operations, self.issues = [], []
        self.results_table.setRowCount(0)
        self.apply_button.setEnabled(False)
        if not self.targets_table.rowCount():
            self.info.setText("Adicione ao menos uma camada-alvo.")
            return
        try:
            source_layer, source_grouped, requested = self.source_geometries_by_key()
            duplicates = {key for key, features in source_grouped.items() if len(features) > 1}
            self.issues.extend(f"Origem: {key} possui mais de uma geometria" for key in duplicates)
            if requested:
                self.issues.extend(f"Origem: {key} não foi encontrada" for key in sorted(requested - set(source_grouped)))
            total_valid = 0
            for row, target_layer, field_name in self.target_rows():
                # Consulta no provedor, equivalente ao filtro que o usuário executa
                # no Console Python do QGIS. Isso evita contagem por varredura local.
                target_grouped = {}
                escaped_field = field_name.replace('"', '""')
                for key in source_grouped:
                    expression = '"{}" = {}'.format(escaped_field, QgsExpression.quotedValue(key))
                    request = QgsFeatureRequest().setFilterExpression(expression)
                    target_grouped[key] = list(target_layer.getFeatures(request))
                valid, problems = 0, 0
                for key, sources in source_grouped.items():
                    targets = target_grouped.get(key, [])
                    if len(sources) != 1:
                        problems += 1
                        continue
                    if len(targets) != 1:
                        target_ids = ", ".join(str(feature.id()) for feature in targets)
                        label = "não encontrado" if not targets else f"possui {len(targets)} feições (IDs: {target_ids})"
                        self.issues.append(f"{target_layer.name()}: {key} {label}")
                        problems += 1
                        continue
                    new_geometry = self.geometry_for_target(sources[0], source_layer, target_layer)
                    old_geometry = QgsGeometry(targets[0].geometry())
                    if new_geometry.type() != target_layer.geometryType():
                        self.issues.append(f"{target_layer.name()}: {key} tem tipo de geometria incompatível")
                        problems += 1
                        continue
                    self.operations.append({
                        "layer": target_layer, "feature_id": targets[0].id(), "key": key,
                        "old": old_geometry, "new": new_geometry,
                    })
                    self.add_preview(target_layer, old_geometry, new_geometry)
                    self.add_result_row(target_layer.name(), key)
                    valid += 1
                total_valid += valid
                result = f"{valid} pronta(s)" + (f"; {problems} pendência(s)" if problems else "")
                self.targets_table.item(row, 2).setText(result)
            # A prévia deve preservar a posição e o zoom escolhidos no mapa principal.
            # A comparação espacial é feita apenas nos mini-mapas do próprio plugin.
            self.iface.mapCanvas().refresh()
            summary = f"Prévia pronta: {total_valid} substituição(ões) válida(s)."
            if self.issues:
                summary += " Pendências: " + " | ".join(self.issues[:4])
                if len(self.issues) > 4:
                    summary += f" (+{len(self.issues) - 4} outras)"
            self.info.setText(summary + " No mapa principal: vermelho é a atual; verde é a nova.")
            self.apply_button.setEnabled(bool(self.operations))
            if self.operations:
                self.results_table.selectRow(0)
        except Exception as error:
            self.info.setText(f"Não foi possível gerar a prévia: {error}")

    def add_result_row(self, layer_name, key):
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(layer_name))
        self.results_table.setItem(row, 1, QTableWidgetItem(key))
        self.results_table.setItem(row, 2, QTableWidgetItem("Pronta"))

    def add_preview(self, layer, old_geometry, new_geometry):
        old_band = QgsRubberBand(self.iface.mapCanvas(), layer.geometryType())
        old_band.setColor(QColor(210, 0, 0))
        old_band.setWidth(3)
        old_band.addGeometry(old_geometry, layer)
        new_band = QgsRubberBand(self.iface.mapCanvas(), layer.geometryType())
        new_band.setColor(QColor(0, 190, 0))
        new_band.setFillColor(QColor(0, 255, 0, 35))
        new_band.setWidth(3)
        new_band.addGeometry(new_geometry, layer)
        self.preview_bands.extend((old_band, new_band))

    def show_selected_overview(self):
        selected = self.results_table.selectionModel().selectedRows()
        if not selected or selected[0].row() >= len(self.operations):
            return
        operation = self.operations[selected[0].row()]
        layer = operation["layer"]
        self.set_overview_canvas(self.old_canvas, "old", operation["old"], layer, QColor(210, 0, 0))
        self.set_overview_canvas(self.new_canvas, "new", operation["new"], layer, QColor(0, 150, 0))
        self.overview_info.setText(
            f"Identificador: {operation['key']}\nCamada: {layer.name()}\n"
            f"Área original: {operation['old'].area():,.2f} m²\n"
            f"Área nova: {operation['new'].area():,.2f} m²"
        )

    def set_overview_canvas(self, canvas, name, geometry, layer, color):
        old_band = self.overview_bands.get(name)
        if old_band is not None:
            old_band.reset()
            canvas.scene().removeItem(old_band)
        canvas.setDestinationCrs(layer.crs())
        band = QgsRubberBand(canvas, layer.geometryType())
        band.setColor(color)
        band.setFillColor(QColor(color.red(), color.green(), color.blue(), 45))
        band.setWidth(3)
        band.addGeometry(geometry, layer)
        self.overview_bands[name] = band
        extent = geometry.boundingBox()
        if not extent.isEmpty():
            extent.scale(1.15)
            canvas.setExtent(extent)
        canvas.refresh()

    def zoom_selected_on_main_canvas(self):
        selected = self.results_table.selectionModel().selectedRows()
        if not selected or selected[0].row() >= len(self.operations):
            return
        operation = self.operations[selected[0].row()]
        extent = operation["old"].boundingBox()
        extent.combineExtentWith(operation["new"].boundingBox())
        extent.scale(1.15)
        self.iface.mapCanvas().setExtent(extent)
        self.iface.mapCanvas().refresh()

    def apply_changes(self):
        if not self.operations:
            return
        answer = QMessageBox.warning(
            self.dialog, "Confirmar substituições em lote",
            f"Aplicar {len(self.operations)} substituição(ões) válida(s)?\n\n"
            "As pendências mostradas na prévia não serão alteradas.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        by_layer = defaultdict(list)
        for operation in self.operations:
            by_layer[operation["layer"]].append(operation)
        started_here = []
        try:
            for layer in by_layer:
                if not layer.isEditable():
                    if not layer.startEditing():
                        raise RuntimeError("Não foi possível iniciar a edição de " + layer.name())
                    started_here.append(layer)
            for layer, changes in by_layer.items():
                for operation in changes:
                    if not layer.changeGeometry(operation["feature_id"], QgsGeometry(operation["new"])):
                        raise RuntimeError(f"Não foi possível alterar {operation['key']} em {layer.name()}")
            for layer in started_here:
                if not layer.commitChanges():
                    errors = layer.commitErrors()
                    raise RuntimeError(f"Falha ao gravar {layer.name()}: {errors[-1] if errors else 'erro desconhecido'}")
        except Exception as error:
            for layer in started_here:
                if layer.isEditable():
                    layer.rollBack()
            QMessageBox.critical(self.dialog, "Alteração não concluída", str(error))
            return
        count = len(self.operations)
        self.clear_preview()
        self.operations = []
        self.apply_button.setEnabled(False)
        QMessageBox.information(self.dialog, "Concluído", f"{count} geometria(s) atualizada(s) com sucesso.")

    def clear_overviews(self):
        for name, band in self.overview_bands.items():
            if band is not None:
                band.reset()
                canvas = self.old_canvas if name == "old" else self.new_canvas
                canvas.scene().removeItem(band)
                self.overview_bands[name] = None
        if hasattr(self, "overview_info"):
            self.overview_info.setText("Gere a prévia e selecione uma substituição válida na lista.")

    def clear_preview(self):
        for band in self.preview_bands:
            band.reset()
            self.iface.mapCanvas().scene().removeItem(band)
        self.preview_bands = []
        self.clear_overviews()
        if self.iface:
            self.iface.mapCanvas().refresh()

    def close_dialog(self):
        self.clear_preview()
        self.dialog.close()
