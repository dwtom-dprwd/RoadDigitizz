from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.core import QgsWkbTypes
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsGeometry
from qgis.core import QgsFeature
from qgis.core import QgsCoordinateTransform
from qgis.core import QgsProject
from qgis.core import Qgis
from qgis.core import QgsPointLocator
from qgis.gui import QgsSnapIndicator


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
            QgsWkbTypes.LineGeometry
        )

        self.bufferBand = QgsRubberBand(
            self.canvas,
            QgsWkbTypes.PolygonGeometry
        )

        self.points = []

        self.snapIndicator = QgsSnapIndicator(self.canvas)

        self.currentMousePoint = None

        self.canvas.setFocus()

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

        print("Cap Style:", capStyle)

        if self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def setJoinStyle(self, joinStyle):

        self.joinStyle = joinStyle

        print("Join Style:", joinStyle)

        if self.currentMousePoint is not None:
            self.updateBufferPreview(self.currentMousePoint)

    def canvasPressEvent(self, event):

        if event.button() == Qt.LeftButton:

            point = self.snapPoint(event.pos())

            print("Clicked:", point)

            self.addVertex(point)

        elif event.button() == Qt.RightButton:

            self.finishDigitizing()

    def canvasMoveEvent(self, event):

        point = self.snapPoint(event.pos())

        self.currentMousePoint = point

        if len(self.points) == 0:
            return

        self.updateLinePreview(point)

        self.updateBufferPreview(point)

    def keyPressEvent(self, event):

        if event.key() == Qt.Key_Backspace:

            self.undoLastVertex()

            event.accept()

            return

        super().keyPressEvent(event)

    def addVertex(self, point):

        self.points.append(point)

        self.rubberBand.addPoint(point)

    def undoLastVertex(self):

        if not self.points:
            return

        self.points.pop()

        print("Undo vertex")

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

        print("Digitizing Finished")

    def saveCenterLine(self):

        layer_points = self.getLayerPoints()

        geometry = QgsGeometry.fromPolylineXY(layer_points)

        print("Geometry:")
        print(geometry.asWkt())

        feature = QgsFeature(self.line_layer.fields())

        feature.setGeometry(geometry)

        result = self.line_layer.addFeature(feature)

        print("addFeature:", result)

        self.line_layer.updateExtents()
        self.line_layer.triggerRepaint()

        self.canvas.refresh()

    def savePolygon(self):

        canvas_line = QgsGeometry.fromPolylineXY(self.points)

        buffer = canvas_line.buffer(
            self.width / 2,
            8,
            self.getCapStyle(),
            self.getJoinStyle(),
            2
        )

        buffer = self.transformGeometryToLayer(buffer)

        feature = QgsFeature(self.polygon_layer.fields())

        feature.setGeometry(buffer)

        result = self.polygon_layer.addFeature(feature)

        print("Polygon addFeature:", result)

    def getLayerPoints(self):
        """
        Mengubah titik dari CRS canvas menjadi CRS layer.
        """

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.line_layer.crs()

        # Jika CRS sama, tidak perlu transformasi
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

        print("Canvas CRS :", canvas_crs.authid())
        print("Layer CRS  :", layer_crs.authid())

        return layer_points

    def transformGeometryToLayer(self, geometry):
        """
        Mengubah geometry dari CRS canvas ke CRS layer.
        """

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

        self.rubberBand.reset(QgsWkbTypes.LineGeometry)

        self.bufferBand.reset(QgsWkbTypes.PolygonGeometry)

    def updateLinePreview(self, tempPoint):

        self.rubberBand.reset(QgsWkbTypes.LineGeometry)

        for p in self.points:
            self.rubberBand.addPoint(p)

        self.rubberBand.addPoint(tempPoint)

    def updateBufferPreview(self, tempPoint):

        points = self.points.copy()
        points.append(tempPoint)

        if len(points) < 2:
            return

        line = QgsGeometry.fromPolylineXY(points)

        polygon = line.buffer(
            self.width / 2,
            8,
            self.getCapStyle(),
            self.getJoinStyle(),
            2
        )

        self.bufferBand.setToGeometry(
            polygon,
            None
        )
