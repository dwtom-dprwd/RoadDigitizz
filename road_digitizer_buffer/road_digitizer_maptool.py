from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsSnapIndicator
from qgis.core import (
    QgsWkbTypes,
    QgsGeometry,
    QgsFeature,
    QgsCoordinateTransform,
    QgsProject,
    Qgis,
    QgsPointLocator,
    QgsDistanceArea
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


class RoadDigitizerMapTool(QgsMapToolEmitPoint):

    def __init__(self, canvas, line_layer, polygon_layer, width):
        super().__init__(canvas)
        self.canvas = canvas
        self.line_layer = line_layer
        self.polygon_layer = polygon_layer
        self.width = width
        self.capStyle = "Flat"
        self.joinStyle = "Round"

        self.rubberBand = QgsRubberBand(
            self.canvas,
            QgsWkbTypes.GeometryType.LineGeometry
        )
        self.bufferBand = QgsRubberBand(
            self.canvas,
            QgsWkbTypes.GeometryType.PolygonGeometry
        )

        self.rubberBand.setColor(QColor(255, 0, 0))
        self.rubberBand.setWidth(1)

        self.bufferBand.setFillColor(QColor(255, 0, 0, 40))
        self.bufferBand.setStrokeColor(QColor(255, 0, 0))
        self.bufferBand.setWidth(1)

        self.points = []
        self.snapIndicator = QgsSnapIndicator(self.canvas)
        self.currentMousePoint = None
        self.canvas.setFocus()

        # Distance calculator
        self.dist_calculator = QgsDistanceArea()
        self._updateDistanceCalculator()

        # Update jika CRS project berubah
        QgsProject.instance().crsChanged.connect(
            self._updateDistanceCalculator
        )

    def getCapStyle(self):

        mapping = {
            "Flat": Qgis.EndCapStyle.Flat,
            "Round": Qgis.EndCapStyle.Round,
            "Square": Qgis.EndCapStyle.Square
        }
        return mapping.get(self.capStyle, Qgis.EndCapStyle.Flat)

    def getJoinStyle(self):

        mapping = {
            "Round": Qgis.JoinStyle.Round,
            "Miter": Qgis.JoinStyle.Miter,
            "Bevel": Qgis.JoinStyle.Bevel
        }
        return mapping.get(
            self.joinStyle,
            Qgis.JoinStyle.Round
        )

    def setWidth(self, width):

        self.width = width
        if self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def setCapStyle(self, capStyle):

        self.capStyle = capStyle
        if self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def setJoinStyle(self, joinStyle):

        self.joinStyle = joinStyle
        if self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def canvasPressEvent(self, event):

        if event.button() == Qt.MouseButton.LeftButton:
            point = self.snapPoint(event.pos())
            self.addVertex(point)

        elif event.button() == Qt.MouseButton.RightButton:
            self.finishDigitizing()

    def canvasMoveEvent(self, event):

        point = self.snapPoint(event.pos())
        self.currentMousePoint = point

        if len(self.points) == 0:
            return

        self.updateLinePreview(point)
        self.updateBufferPreview(point)

    def keyPressEvent(self, event):

        if event.key() == Qt.Key.Key_Backspace:
            self.undoLastVertex()
            event.accept()
            return

        elif event.key() == Qt.Key.Key_Escape:
            self.cancelDigitizing()
            event.accept()
            return

        super().keyPressEvent(event)

    def addVertex(self, point):

        self.points.append(point)
        self.rubberBand.addPoint(point)

    def undoLastVertex(self):

        if len(self.points) <= 1:
            return

        self.points.pop()
        self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)

        for p in self.points:
            self.rubberBand.addPoint(p)

        self.bufferBand.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

        if len(self.points) >= 2 and self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def cancelDigitizing(self):

        self.resetPreview()
        self.currentMousePoint = None
        self.snapIndicator.setMatch(
            QgsPointLocator.Match()
        )

    def snapPoint(self, pos):

        snappingUtils = self.canvas.snappingUtils()
        match = snappingUtils.snapToMap(pos)

        if match.isValid():
            self.snapIndicator.setMatch(match)
            return match.point()

        self.snapIndicator.setMatch(QgsPointLocator.Match())
        return self.toMapCoordinates(pos)

    def finishDigitizing(self):

        if len(self.points) < 2:
            return

        self.saveCenterLine()
        self.savePolygon()
        self.resetPreview()
        self.snapIndicator.setMatch(
            QgsPointLocator.Match()
        )

    def saveCenterLine(self):

        layer_points = self.getLayerPoints()
        geometry = QgsGeometry.fromPolylineXY(layer_points)
        feature = QgsFeature(self.line_layer.fields())
        feature.setGeometry(geometry)

        self.line_layer.addFeature(feature)
        self.line_layer.updateExtents()
        self.line_layer.triggerRepaint()
        self.canvas.refresh()

    def savePolygon(self):

        canvas_line = QgsGeometry.fromPolylineXY(self.points)
        buffer_distance = self.convert_meters_to_canvas_units(
            self.width / 2
        )

        buffer = canvas_line.buffer(
            buffer_distance,
            8,
            self.getCapStyle(),
            self.getJoinStyle(),
            2
        )
        buffer = self.transformGeometryToLayer(buffer)

        feature = QgsFeature(self.polygon_layer.fields())
        feature.setGeometry(buffer)
        self.polygon_layer.addFeature(feature)

    def getLayerPoints(self):
        """Mengubah titik dari CRS canvas menjadi CRS layer."""

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.line_layer.crs()

        if canvas_crs == layer_crs:
            return self.points

        transform = QgsCoordinateTransform(
            canvas_crs,
            layer_crs,
            QgsProject.instance()
        )

        layer_points = []
        for pt in self.points:
            layer_points.append(transform.transform(pt))

        return layer_points

    # Cache QgsDistanceArea for future CRS-aware calculations.
    # Updated whenever the project CRS changes.
    def _updateDistanceCalculator(self):
        """Perbarui dist_calculator dengan CRS canvas dan ellipsoid project"""
        project = QgsProject.instance()
        canvas_crs = self.canvas.mapSettings().destinationCrs()

        self.dist_calculator.setSourceCrs(
            canvas_crs,
            project.transformContext()
        )
        self.dist_calculator.setEllipsoid(
            project.ellipsoid()
        )

    def convert_meters_to_canvas_units(self, meters):

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        return self.dist_calculator.convertLengthMeasurement(
            meters,
            canvas_crs.mapUnits()
        )

    def transformGeometryToLayer(self, geometry):
        """Mengubah geometry dari CRS canvas ke CRS layer."""

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.polygon_layer.crs()

        if canvas_crs == layer_crs:
            return geometry

        transform = QgsCoordinateTransform(
            canvas_crs,
            layer_crs,
            QgsProject.instance()
        )

        geom = QgsGeometry(geometry)
        geom.transform(transform)
        return geom

    def resetPreview(self):

        self.points.clear()
        self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self.bufferBand.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

    def updateLinePreview(self, tempPoint):

        self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)
        for p in self.points:
            self.rubberBand.addPoint(p)
        self.rubberBand.addPoint(tempPoint)

    def updateBufferPreview(self, tempPoint):

        points = self.points.copy()
        points.append(tempPoint)

        if len(points) < 2:
            return

        line = QgsGeometry.fromPolylineXY(points)
        buffer_distance = self.convert_meters_to_canvas_units(
            self.width / 2
        )

        polygon = line.buffer(
            buffer_distance,
            8,
            self.getCapStyle(),
            self.getJoinStyle(),
            2
        )
        self.bufferBand.setToGeometry(
            polygon,
            None
        )
