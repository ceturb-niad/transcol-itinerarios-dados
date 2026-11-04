"""Testes do conversor. Rodar da raiz do repositório:

    python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import converter as c  # noqa: E402

KML_OK = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>doc</name>
<Folder><name>18_10_2026</name>
  <Folder><name>Serra</name>
    <Folder><name>835</name>
      <Placemark><name>835I</name><LineString><coordinates>
        -40.1234567891,-20.1234567891,12.5 -40.1234567891,-20.1234567891,0 -40.2,-20.2,0
      </coordinates></LineString></Placemark>
      <Placemark><name>835V_A</name><LineString><coordinates>-40.1,-20.1,0 -40.2,-20.2,0</coordinates></LineString></Placemark>
    </Folder>
  </Folder>
  <Folder><name>Noturno</name>
    <Folder><name>Cariacica</name>
      <Folder><name>735_TST</name>
        <Placemark><name>735I_P</name><LineString><coordinates>-40.1,-20.1,0 -40.2,-20.2,0</coordinates></LineString></Placemark>
      </Folder>
    </Folder>
  </Folder>
  <Folder><name>Volta Direto</name>
    <Placemark><name>649I_B (Pleno Voo)</name><LineString><coordinates>-40.1,-20.1,0 -40.2,-20.2,0</coordinates></LineString></Placemark>
  </Folder>
</Folder></Document></kml>"""


def kml_em_arquivo(texto):
    d = tempfile.mkdtemp()
    p = Path(d) / "a.kml"
    p.write_text(texto, encoding="utf-8")
    return p


class TestConversao(unittest.TestCase):
    def setUp(self):
        self.fc, self.versao, _ = c.converter(kml_em_arquivo(KML_OK))
        self.por_nome = {f["properties"]["nome"]: f for f in self.fc["features"]}

    def test_raiz_e_descartada_do_caminho(self):
        self.assertEqual(self.versao, "18_10_2026")
        for f in self.fc["features"]:
            self.assertNotIn("18_10_2026", f["properties"]["caminho"])

    def test_caso_comum(self):
        p = self.por_nome["835I"]["properties"]
        self.assertEqual((p["caminho"], p["grupo"], p["subgrupo"], p["pasta_linha"], p["linha"]),
                         ("Serra/835", "Serra", None, "835", "835"))
        self.assertEqual((p["codigo"], p["sentido"], p["variante"]), ("835", "I", None))

    def test_subgrupo_em_noturno(self):
        p = self.por_nome["735I_P"]["properties"]
        self.assertEqual((p["grupo"], p["subgrupo"], p["pasta_linha"], p["linha"], p["variante"]),
                         ("Noturno", "Cariacica", "735_TST", "735_TST", "P"))

    def test_sem_pasta_linha_usa_codigo(self):
        p = self.por_nome["649I_B (Pleno Voo)"]["properties"]
        self.assertEqual((p["pasta_linha"], p["linha"], p["obs"], p["caminho"]),
                         (None, "649", "Pleno Voo", "Volta Direto"))

    def test_geometria_2d_6_casas_sem_repeticao(self):
        coords = self.por_nome["835I"]["geometry"]["coordinates"]
        self.assertEqual(coords, [[-40.123457, -20.123457], [-40.2, -20.2]])

    def test_chaves_unicas_e_validacao(self):
        self.assertEqual(len({f["properties"]["chave"] for f in self.fc["features"]}), 4)
        c.validar(self.fc)

    def test_nome_repetido_gera_chave_distinta(self):
        dup = KML_OK.replace("<name>835V_A</name>", "<name>835I</name>")
        fc, _, _ = c.converter(kml_em_arquivo(dup))
        chaves = [f["properties"]["chave"] for f in fc["features"]]
        self.assertEqual(len(set(chaves)), len(chaves))

    def test_nome_fora_do_padrao_nao_quebra(self):
        fora = KML_OK.replace("<name>835V_A</name>", "<name>Teste 12</name>")
        fc, _, st = c.converter(kml_em_arquivo(fora))
        self.assertEqual(st["fora_do_padrao"], 1)
        p = next(f for f in fc["features"] if f["properties"]["nome"] == "Teste 12")["properties"]
        self.assertEqual(p["linha"], "835")  # herda a pasta-linha


class TestFalhas(unittest.TestCase):
    def assertFalha(self, texto):
        with self.assertRaises(c.ErroConversao):
            fc, _, _ = c.converter(kml_em_arquivo(texto))
            c.validar(fc)

    def test_xml_truncado(self):
        self.assertFalha(KML_OK[:600])

    def test_duas_raizes(self):
        self.assertFalha(KML_OK.replace("</Folder></Document>", "</Folder><Folder><name>x</name></Folder></Document>"))

    def test_coordenada_invalida(self):
        trecho = "-40.1,-20.1,0 -40.2,-20.2,0"
        self.assertIn(trecho, KML_OK)
        self.assertFalha(KML_OK.replace(trecho, "abc,def", 1))

    def test_coordenada_fora_do_intervalo(self):
        trecho = "-40.1,-20.1,0 -40.2,-20.2,0"
        self.assertFalha(KML_OK.replace(trecho, "-400,-20,0 -40.2,-20.2,0", 1))

    def test_linestring_com_um_ponto(self):
        trecho = "-40.1,-20.1,0 -40.2,-20.2,0"
        self.assertFalha(KML_OK.replace(trecho, "-40.1,-20.1,0", 1))

    def test_zero_features(self):
        vazio = '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder><name>r</name></Folder></Document></kml>'
        self.assertFalha(vazio)


class TestManifesto(unittest.TestCase):
    def test_primeira_execucao(self):
        m, mudou = c.montar_manifesto("h1", 10, "r", None, "2026-11-04T12:00:00Z")
        self.assertTrue(mudou)
        self.assertEqual(m["dados_atualizados_em"], "2026-11-04T12:00:00Z")

    def test_hash_igual_preserva_data(self):
        ant = {"hash_origem": "h1", "dados_atualizados_em": "2026-11-01T00:00:00Z"}
        m, mudou = c.montar_manifesto("h1", 10, "r", ant, "2026-11-04T12:00:00Z")
        self.assertFalse(mudou)
        self.assertEqual(m["dados_atualizados_em"], "2026-11-01T00:00:00Z")
        self.assertEqual(m["verificado_em"], "2026-11-04T12:00:00Z")

    def test_hash_diferente_atualiza_data(self):
        ant = {"hash_origem": "h0", "dados_atualizados_em": "2026-11-01T00:00:00Z"}
        m, mudou = c.montar_manifesto("h1", 10, "r", ant, "2026-11-04T12:00:00Z")
        self.assertTrue(mudou)
        self.assertEqual(m["dados_atualizados_em"], "2026-11-04T12:00:00Z")


class TestExecucao(unittest.TestCase):
    def test_ponta_a_ponta_e_falha_nao_grava(self):
        d = Path(tempfile.mkdtemp())
        kml = kml_em_arquivo(KML_OK)
        self.assertEqual(c.main(["--kml", str(kml), "--saida", str(d / "s"), "--estado", str(d / "m.json")]), 0)
        self.assertEqual(json.loads((d / "s" / "itinerarios.geojson").read_text())["type"], "FeatureCollection")
        self.assertNotIn("verificado_em", json.loads((d / "m.json").read_text()))
        ruim = kml_em_arquivo("<kml>")
        self.assertEqual(c.main(["--kml", str(ruim), "--saida", str(d / "s2")]), 1)
        self.assertFalse((d / "s2").exists())


if __name__ == "__main__":
    unittest.main()
