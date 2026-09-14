def classFactory(iface):
    """Ponto de entrada exigido pelo gerenciador de complementos do QGIS."""
    from .substituir_geometria import SubstituirGeometriaPlugin
    return SubstituirGeometriaPlugin(iface)
