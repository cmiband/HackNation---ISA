"""Canned AI results for UI development (AI_MOCK=1): no LLM, no embedding model, no vector DB."""

from contracts.enums import TriageKind
from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    DocumentInput,
    DraftInput,
    DraftResult,
    Health,
    QuestionMatch,
    RequestQuestion,
    SimilarCase,
    Triage,
)

MOCK_WARNING = (
    "TRYB DEMONSTRACYJNY (AI_MOCK=1): to przykładowy wynik, a nie analiza tego wniosku. "
    "Ustaw AI_MOCK=0 w pliku .env i uruchom aplikację ponownie."
)


class MockAIService:
    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        questions = [
            "Liczba uczniów w szkołach podstawowych w Bydgoszczy.",
            "Liczba uczniów cudzoziemców w poszczególnych szkołach podstawowych w Bydgoszczy.",
        ]
        return AnalyzeResult(
            case_id=input_data.case_id,
            text=input_data.text or f"(mock) text of {input_data.filename}",
            parse_method="text" if input_data.text is not None else "docx",
            summary="Prośba o zestawienie liczby uczniów, w tym cudzoziemców, w bydgoskich szkołach podstawowych.",
            subject="liczby uczniów w szkołach podstawowych",
            applicant="Jan Testowy",
            questions=[RequestQuestion(text=q, departments=["WE"]) for q in questions],
            suggested_departments=["WE"],
            similar_cases=[
                SimilarCase(
                    case_id=1,
                    score=0.85,
                    matches=[
                        QuestionMatch(
                            question=questions[0],
                            archived_question="Aktualne zestawienie liczby uczniów w szkołach podstawowych.",
                            score=0.9,
                        )
                    ],
                )
            ],
            warnings=[MOCK_WARNING],
            triage=Triage(
                kind=TriageKind.DUPLICATE,
                duplicate_case_ids=[1],
                reason="(mock) Practically the same questions were already handled in an earlier case.",
            ),
        )

    def draft_response(self, input_data: DraftInput) -> DraftResult:
        body = (
            "w odpowiedzi na wniosek o udostępnienie informacji publicznej w zakresie liczby uczniów w szkołach "
            "podstawowych, na podstawie informacji przygotowanych przez komórkę merytoryczną, tj. Wydział Edukacji "
            "i Sportu Urzędu Miasta Bydgoszczy, uprzejmie informuję, co następuje.\n"
            "Ad 1\nW roku szkolnym 2024/2025 do szkół podstawowych prowadzonych przez Miasto Bydgoszcz uczęszczało "
            "21 437 uczniów.\nAd 2\n[brak odpowiedzi komórki merytorycznej]"
        )
        return DraftResult(
            body=body,
            values_to_verify=["2024/2025", "21 437", "[brak odpowiedzi komórki merytorycznej]"],
            unanswered_questions=[2] if len(input_data.questions) > 1 else [],
            notes="(mock) Brak danych o cudzoziemcach w przekazanych dokumentach.",
            warnings=[MOCK_WARNING],
        )

    def extract_text(self, document: DocumentInput) -> str:
        if document.text is not None:
            return document.text
        return (
            f"(mock) Treść pliku {document.filename}. Wnioskodawca: Jan Kowalski, ul. Długa 5, 85-001 Bydgoszcz, "
            "tel. 601 234 567, e-mail: jan.kowalski@example.com, PESEL 90010112349."
        )

    def delete_case(self, case_id: int) -> None:
        return None

    def health(self) -> Health:
        return Health(status="ok", vector_db_count=10, departments_loaded=29, llm_provider="mock")
