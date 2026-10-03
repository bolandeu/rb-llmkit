Запрос: {{intent.text}}
Версия контекста: {{context.version}}
{{#context.knowledge}}- {{.}}
{{/context.knowledge}}{{^context.knowledge}}Знаний нет.
{{/context.knowledge}}