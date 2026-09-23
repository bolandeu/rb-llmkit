"""Провайдеры по подписке: свой вызов модели вместо `litellm.acompletion`.

У каждого модуля функция `acompletion(**kwargs)` с сигнатурой LiteLLM,
возвращающая `litellm.ModelResponse`, — ядро и Instructor не видят разницы.
Решения портированы из iva-agent (github.com/smixs/iva-agent).
"""
