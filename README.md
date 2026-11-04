# Dados dos itinerários Transcol GV

Converte o KML de itinerários (editado no Google Earth e publicado em outro repositório) em GeoJSON e o publica no GitHub Pages, duas vezes por dia. O front lê o resultado; este repositório não tem interface.

Documento do projeto: *Visualizador web de itinerários Transcol GV: aplicação V1 (piloto)*.

## URLs estáveis

- `https://<organização>.github.io/<este-repositório>/itinerarios.geojson`
- `https://<organização>.github.io/<este-repositório>/manifest.json`

## Contrato de dados

GeoJSON `FeatureCollection` de `LineString` em 2D (sem Z), coordenadas com 6 casas decimais, vértices consecutivos repetidos removidos. A pasta raiz do KML (hoje com nome de data, ex.: `18_10_2026`) **não** entra nos atributos; o nome dela vai para `versao_kml` no manifesto.

| Campo | Exemplo | Regra |
| --- | --- | --- |
| `caminho` | `Noturno/Cariacica/735_TST` | pastas sob a raiz, separadas por `/`; vazio se o placemark estiver direto na raiz |
| `grupo` | `Noturno` | primeira pasta sob a raiz; mistura município e tipo de serviço |
| `subgrupo` | `Cariacica` | segunda pasta, só quando há três níveis (Noturno, Praias); senão nulo |
| `pasta_linha` | `735_TST` | pasta mais interna quando há pelo menos grupo e pasta; nulo em Volta Direto e Bike GV |
| `linha` | `735_TST` | `pasta_linha`, ou `codigo` se não houver pasta, ou `nome` como último recurso |
| `nome` | `735I_P` | nome do placemark |
| `codigo` | `735` | dígitos iniciais do nome |
| `sentido` | `I` ou `V` | letra após os dígitos |
| `variante` | `P` | sufixo após `_` |
| `obs` | `Pleno Voo` | texto entre parênteses no nome |
| `chave` | `Noturno/Cariacica/735_TST/735I_P` | `caminho/nome`; identificador da feature; `#2`, `#3` se houver nome repetido na mesma pasta |

Identidade de uma linha: o par (`grupo`, `linha`). Só `linha` não basta: em 4 casos (4216, 649, 675, 697) o mesmo valor aparece em `Volta Direto` e em outro grupo.

Manifesto: `dados_atualizados_em`, `verificado_em` (ambos em UTC, ISO 8601), `hash_origem` (SHA-256 do KML), `n_features`, `versao_kml`.

Mudanças no contrato são aditivas: campo novo pode; renomear ou remover não pode. Se uma quebra for inevitável, publica-se `itinerarios_v2.geojson` ao lado do atual.

## Como funciona

1. `schedule` (12:15 e 00:15 de Brasília) ou disparo manual.
2. Baixa o KML da URL em `vars.KML_URL`.
3. `scripts/converter.py` converte e valida (GeoJSON válido, ao menos uma feature, campos obrigatórios). Qualquer falha encerra com erro: nada é publicado e o Pages mantém o último deploy bom.
4. Publica `_site/` (GeoJSON e manifesto, com `verificado_em` atualizado) no Pages.
5. Só depois do deploy, se o hash do KML mudou, commita `manifest.json` na raiz. Esse arquivo guarda o hash anterior e a data dos dados; sem ele a data não sobrevive entre execuções.

O conversor usa só a biblioteca padrão do Python. Não há GDAL.

## Configuração inicial (uma vez, pela conta do administrador)

1. Criar o repositório na organização e subir estes arquivos no branch padrão.
2. Settings > Pages > Source: **GitHub Actions**.
3. Settings > Secrets and variables > Actions > Variables: criar `KML_URL` com a URL pública do KML no Pages do repositório de origem.
4. Criar o workflow e alterar o cron sempre com a conta que deve receber o e-mail de falha, e manter as notificações do Actions ativas nela.
5. Rodar o workflow manualmente (Actions > Publicar itinerários > Run workflow) e conferir as duas URLs.

Se o repositório ficar 60 dias sem atividade, o GitHub desativa o agendamento. O commit do `manifest.json` conta como atividade, mas só ocorre quando o KML muda. A defesa é o `verificado_em` visível no front.

## Desenvolvimento local (VS Code no WSL2/Ubuntu)

```bash
python3 --version                       # 3.10 ou superior
python -m unittest discover -s tests -v
python scripts/converter.py --kml caminho/para/itinerarios.kml --saida _site --estado /tmp/estado.json
```

Em execução local, aponte `--estado` para fora do repositório (por exemplo `/tmp/estado.json`), para não criar um `manifest.json` que o workflow depois trataria como estado.
