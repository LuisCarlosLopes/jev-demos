"""Hello, Jev: uma chamada, três tipos de pergunta, respostas tipadas com probabilidade.

    python hello_jev.py
    python hello_jev.py "O suporte demorou 3 dias e ninguém resolveu meu problema."

Só usa a biblioteca padrão. A chave vem de TYPESAFE_API_KEY (variável de ambiente ou
arquivo .env ao lado deste script ou em ../skill-validator/.env).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # fixo em vez de jev-latest, para resultados comparáveis
PRICE_PER_MTOK_INPUT = 0.042  # USD; tokens de saída são gratuitos

DEFAULT_TEXT = "Comprei há duas semanas e o produto já quebrou. Quero meu dinheiro de volta!"

# O estado é o material a julgar. As perguntas são independentes e rodam em paralelo.
QUESTIONS = {
    # Noul: sim/não como probabilidade (0 a 1).
    "is_complaint": {
        "type": "noul",
        "instructions": "A mensagem do cliente é uma reclamação sobre um produto ou serviço?",
        "criteria": {
            "true": "O autor expressa insatisfação com um produto ou serviço.",
            "false": "Mensagem neutra, positiva ou apenas informativa.",
        },
    },
    # Choice: uma opção entre várias, com a distribuição inteira e a confiança.
    "topic": {
        "type": "choice",
        "instructions": "Qual é o assunto principal da mensagem do cliente?",
        "criteria": {
            "cobranca": "Cobranças, reembolsos, faturas ou problemas de pagamento.",
            "defeito": "O produto está quebrado, com defeito ou não funciona.",
            "entrega": "Atrasos na entrega, pacotes perdidos ou danificados.",
            "atendimento": "Qualidade ou rapidez do atendimento ao cliente.",
            "outro": "Nenhum dos anteriores.",
        },
    },
    # Score: nota numa rubrica ordenada; pode cair entre dois níveis.
    "urgency": {
        "type": "score",
        "instructions": "Avalie a urgência de uma resposta humana à mensagem do cliente.",
        "criteria": [
            "Sem urgência; apenas informativa.",
            "Urgência baixa; pode esperar alguns dias.",
            "Urgência alta; o cliente espera resposta em breve.",
            "Crítica; o cliente ameaça cancelar, processar ou escalar.",
            "Baixa; informar mais com retorno"
        ],
    },
}


def load_api_key() -> str:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    here = Path(__file__).resolve().parent
    for env_file in (here / ".env", here.parent / "skill-validator" / ".env"):
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "TYPESAFE_API_KEY" and value.strip():
                    return value.strip().strip("\"'")
    sys.exit("Defina TYPESAFE_API_KEY (variável de ambiente ou arquivo .env).")


def ask_jev(state: str, questions: dict, api_key: str) -> dict:
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"API HTTP {error.code}: confira a chave e o contrato da requisição.")
    except urllib.error.URLError as error:
        sys.exit(f"Falha de conexão: {error.reason}")


def bar(probability: float, width: int = 20) -> str:
    filled = round(probability * width)
    return "█" * filled + "░" * (width - filled)


def main() -> None:
    text = " ".join(sys.argv[1:]) or DEFAULT_TEXT
    api_key = load_api_key()

    started = time.perf_counter()
    data = ask_jev(text, QUESTIONS, api_key)
    elapsed_ms = (time.perf_counter() - started) * 1000
    answers = data["answers"]

    print(f'\nTexto: "{answers}"\n')

    print(f'\nTexto: "{text}"\n')

    noul = answers["is_complaint"]
    print(f"Noul   é reclamação?  {bar(noul['noul'])} {noul['noul']:.0%}")

    choice = answers["topic"]
    print(f"Choice assunto: {choice['choice']}  (confiança {choice['confidence']:.0%})")
    for option, p in sorted(choice["probabilities"].items(), key=lambda kv: -kv[1]):
        print(f"         {option:<12} {bar(p)} {p:.0%}")

    score = answers["urgency"]
    top = len(QUESTIONS["urgency"]["criteria"]) - 1
    print(f"Score  urgência: {score['score']:.2f} de {top}  (confiança {score['confidence']:.0%})")
    print(f"         nível mais provável: {QUESTIONS['urgency']['criteria'][round(score['score'])]}")

    usage = data.get("usage", {})
    cost = usage.get("input_tokens", 0) * PRICE_PER_MTOK_INPUT / 1_000_000
    print(
        f"\n{data['model']} · {elapsed_ms:.0f} ms · {usage.get('input_tokens', '?')} tokens de "
        f"entrada · ~US$ {cost:.6f}"
    )

    # É aqui que o Jev vira código: decisão por limiar, sem interpretar texto livre.
    if noul["noul"] >= 0.8 and score["score"] >= 2:
        print("Ação: encaminhar para atendimento humano com prioridade.")
    elif choice["confidence"] < 0.6:
        print("Ação: confiança baixa, mandar para revisão (ou para um LLM).")
    else:
        print("Ação: fila normal.")


if __name__ == "__main__":
    main()
