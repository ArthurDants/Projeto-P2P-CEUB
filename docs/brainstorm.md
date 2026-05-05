# Brainstorm — Decisões iniciais

Data: 2026-05-04

Objetivo: coletar alternativas e decisões de alto nível antes de qualquer mudança de código.

Principais restrições:
- Não gerar regressões no código existente; mudanças invasivas só após aprovação.
- Sempre apresentar 2–3 abordagens e recomendar uma.
- Testes e verificações automáticas obrigatórias para qualquer implementação.

Perguntas clarificadoras (próximo passo — uma por mensagem):
1. Qual é o escopo funcional das tarefas 01, 02, 03 (uma frase cada)?
2. Preferência por abordagem incremental (feature flags / branches) ou implementação direta?
3. Critérios de aceitação e testes automatizados esperados?

Opções iniciais (resumo):

Opção A — Mudanças Não-Invasivas (recomendado)
- Descrição: implementar funcionalidade como módulos/arquivos novos, sem tocar caminhos críticos existentes.
- Vantagens: mínimo risco, fácil rollback, fácil revisões pequenas.
- Desvantagens: pode precisar de pequenas adaptações de integração.

Opção B — Refatoração controlada + Implementação
- Descrição: ajustar estruturas existentes para acomodar nova funcionalidade e então implementar.
- Vantagens: design mais limpo a longo prazo.
- Desvantagens: maior superfície de mudança; exigir mais testes.

Opção C — Implementação direta em arquivos existentes
- Descrição: editar arquivos centrais para adicionar comportamento.
- Vantagens: implementação rápida.
- Desvantagens: maior risco de regressão — NÃO RECOMENDADO sem aprovação explícita.

Recomendação inicial: seguir Opção A (não-invasiva) e validar com testes. Se houver consenso por refatoração, planejar refatoração em tarefa separada.

Checklist de segurança anti-regressão:
- Sempre criar branch de trabalho (não master/main).
- Escrever/rodar testes unitários antes de alterar código (TDD).
- Executar toda suíte de testes existente e checar lint.
- Fazer commits pequenos e frequentes.

Próximo passo: aguardar a resposta do usuário às perguntas clarificadoras acima; depois gerar o spec e o plano detalhado.
