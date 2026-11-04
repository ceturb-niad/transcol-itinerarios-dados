# Itinerários Transcol GV: dados em GeoJSON

GeoJSON dos itinerários das linhas do Transcol GV, gerado automaticamente a partir do KML de itinerários mantido pela CETURB/ES e atualizado duas vezes por dia.

## Como acessar

```
https://ceturb-niad.github.io/transcol-itinerarios-dados/itinerarios.geojson
https://ceturb-niad.github.io/transcol-itinerarios-dados/manifest.json
```

São arquivos estáticos: um `GET` devolve o arquivo inteiro (cerca de 9 MB) e qualquer filtro é feito por quem consome.

```bash
curl -O https://ceturb-niad.github.io/transcol-itinerarios-dados/itinerarios.geojson
```

## Atualização

O GeoJSON é regenerado por volta das 12:15 e 00:15 (horário de Brasília). O horário pode atrasar, e o cache do navegador pode adiar a exibição por alguns minutos. O arquivo `manifest.json` informa o estado dos dados:

| Campo | Significado |
| --- | --- |
| `dados_atualizados_em` | Quando o KML de origem mudou pela última vez (UTC, ISO 8601) |
| `verificado_em` | Última verificação bem-sucedida (UTC) |
| `hash_origem` | SHA-256 do KML de origem |
| `n_features` | Número de features no GeoJSON |
| `versao_kml` | Identificação da versão do KML de origem |

`dados_atualizados_em` antigo com `verificado_em` recente significa que nada mudou no KML. Um `verificado_em` parado há mais de um dia indica que a atualização está interrompida.

## Formato dos dados

`FeatureCollection` de `LineString`, em longitude e latitude (graus, WGS 84), sem altitude, com 6 casas decimais. Cada feature é um trecho de itinerário (ida ou volta, ou uma variante).

| Campo | Exemplo | Descrição |
| --- | --- | --- |
| `caminho` | `Noturno/Cariacica/735_TST` | Pastas de origem, separadas por `/` |
| `grupo` | `Noturno` | Primeiro nível de organização; mistura município e tipo de serviço |
| `subgrupo` | `Cariacica` | Segundo nível, quando existe; senão nulo |
| `pasta_linha` | `735_TST` | Pasta da linha, quando existe; senão nulo |
| `linha` | `735_TST` | Identificador da linha |
| `nome` | `735I_P` | Nome do itinerário |
| `codigo` | `735` | Código numérico |
| `sentido` | `I` ou `V` | Ida ou volta |
| `variante` | `P` | Variante do itinerário, quando existe |
| `obs` | `Pleno Voo` | Observação, quando existe |
| `chave` | `Noturno/Cariacica/735_TST/735I_P` | Identificador único da feature |

Para identificar uma linha, use o par `grupo` e `linha`: em alguns casos o mesmo valor de `linha` aparece em grupos diferentes.

Novos campos podem ser acrescentados ao longo do tempo; os existentes não são renomeados nem removidos.