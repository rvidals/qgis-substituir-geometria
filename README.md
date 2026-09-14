# Substituir geometria com pré-visualização

Complemento para QGIS 3 que substitui geometrias em lote por associação de atributos, sempre com pré-visualização.

## Instalação para teste

1. Copie a pasta `substituir_geometria` para a pasta de complementos do seu perfil do QGIS. No Windows, normalmente ela fica em `%APPDATA%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins`.
2. Reinicie o QGIS ou use **Complementos > Gerenciar e instalar complementos** e ative **Substituir geometria**.
3. Abra **Substituir geometria > Substituir geometria** ou use o ícone na barra própria do complemento.

O complemento também cria uma barra de ferramentas própria, móvel e acoplável. Arraste a alça à esquerda do ícone para posicioná-la onde preferir no QGIS.

## Uso

1. Escolha o modo de operação:
   - **Uma geometria para vários identificadores**: selecione uma única geometria corrigida e informe os RIPs que devem recebê-la. Esse modo não exige nenhum atributo na camada de origem. Sem seleção, é usada a primeira feição da origem.
   - **Várias geometrias por identificador**: escolha também o campo identificador da origem (por exemplo, `rip`). Cada geometria será associada ao mesmo valor encontrado na camada-alvo.
2. Informe os RIPs/identificadores, um por linha, vírgula ou ponto e vírgula. No modo de várias geometrias, esse filtro é opcional; em branco, todas as feições da origem são consideradas.
3. Escolha uma camada-alvo, clique em **Adicionar camada-alvo** e selecione o campo identificador dela. Repita para cada camada a atualizar; os campos podem ter nomes diferentes.
   Use o botão **Remover** da própria linha se incluir uma camada por engano.
4. Clique em **Atualizar prévia**. A tabela mostra o resultado por camada; no mapa, a feição existente aparece em vermelho e a geometria nova em verde.
5. Confirme a prévia e clique em **Aplicar substituições válidas**.

O complemento reprojeta as geometrias quando as camadas usam SRCs diferentes. Por segurança, associações sem correspondência ou com mais de uma feição na origem/destino são apresentadas como pendência e não são gravadas. Ele só inicia e grava uma sessão de edição própria se a camada-alvo ainda não estiver em edição.

As correspondências da camada-alvo são localizadas por filtro do próprio provedor de dados do QGIS. Em caso de pendência por mais de uma feição, a prévia mostra os IDs retornados para facilitar a conferência.

## Comparação visual antes/depois

Depois de gerar a prévia, selecione uma linha em **Substituições válidas**. Na lateral direita, o painel **Original** mostra a geometria atual em vermelho e o painel **Nova geometria** mostra a substituta em verde. Ambos se ajustam à feição selecionada e exibem o identificador, a camada e as áreas antes/depois. Use **Ampliar no mapa principal** para localizar essa comparação no mapa do projeto.

Atualizar a prévia não muda o zoom nem a posição do mapa principal do QGIS.
