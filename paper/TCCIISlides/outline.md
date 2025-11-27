# Slides TCC II - Outline

------ Introdução ------

- Slide inicial
- Introdução
  - Televisão -> Internet -> consumo em video sob demanda
  - Distribuição de conteúdo -> CDN (replicação de serviços)
- O problema
  - Balanceador de carga é peça fundamental
  - Armazenamento persistente frequentemente é gargalo -> Uso de memória principal (como cache) -> Serviços de distribuição de conteúdo não necessariamente utilizam muito processamento
  - Lacuna crítica nas estratégias convencionais de balanceamento de carga

------ Fundamentação teórica ------

- Fundamentação teórica
  - Balanceadores de carga (à nível de aplicação e rede), balanceamento dinâmico;
  - MPEG-DASH;
  - Servidores de distribuição de conteúdo e CDNs (incluindo o funcionamento de cache);
    - (Imagem) Estrura básica de uma CDN;
    - (Imagem) Fluxo detalhado de múltiplas camadas de caching em CDNs;
  - Monitoramento de memória (APIs fornecidas pelo OS);
  - Interpretação de dados desatualizados;
  - Virtualização de redes para simulação de cenários (incluindo Containers Linux);
- Trabalhos relacionados
  - NGINX
  - HAProxy
  - Novel Weight Assignment load balancing algorithm for cloud apps 2023
  - Web Server performance Improvement 2021 Review
  - Dynamic Load Balancing for Efficient Video Streaming Service 2015
  - Data Allocation and Dynamic Load Balancing for Distributed Video Storage Server 1999

------ Proposta ------

- O algoritmo
  - Funcionamento: Algoritmo probabilístico, dois momentos independentes (atualização da distribuição de probabilidade e seleção do servidor), em paralelo os servidores enviarão sua informação de carga;
  - Equação basic_li
  - Determinação do arrive_t
  - Determinação da carga
  - Determinação dos coeficientes CM e CD
  - Pseudo-código: Atualização da distribuição de probabilidade
- Requisitos tecnológicos
  - 4 aplicações: Servidor de conteúdo, cliente, balanceador de carga, servidor MQTT
  - (Imagem) arquitetura do sistema

------ Implementação ------

- Ambiente: Virtualizado, uma máquina física apenas (WSL2)
- Organização do conteúdo - Docker bind mounts
- Módulos: Principais (MPEG-DASH, balanceador de carga, gerador de carga) e auxiliares (broker MQTT, painel de monitoramento em tempo real, coletor de métricas) (incluir todos os detalhes de implementação aqui)
- Geração de conteúdo 
  - Comando
  - Especificações do comando

------ Experimentos e resultados ------

- Cenários de teste
  - Descrição; Tabela com os cenários;
  - Estratégias de balanceamento avaliadas;
- Resultados
  - Qualidade
  - Bitrate
  - Número de stalls
  - Latência
- Análise dos resultados

------ Conclusão ------

- Validação das hipóteses
- Fatores determinantes do desempenho
  - Heterogeneidade como fator crítico
  - Concorrência como teste de estresse
- Contribuições do trabalho (montar lista);
- Limitações (montar lista);
- Trabalhos futuros (montar lista);
- Reprodutibilidade do experimento;
- Considerações finais;


