"""Canned AI results for UI development (AI_MOCK=1): no LLM, no embedding model, no vector DB."""

from datetime import date

from ai_service.drafting.letter import Letter, placeholders
from contracts.enums import TriageKind
from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    DraftInput,
    DraftResult,
    Health,
    QuestionMatch,
    RequestQuestion,
    SimilarCase,
    Triage,
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
            triage=Triage(
                kind=TriageKind.DUPLICATE,
                duplicate_case_ids=[1],
                reason="(mock) Practically the same questions were already handled in an earlier case.",
            ),
        )

    def draft_response(self, input_data: DraftInput) -> DraftResult:
        kind = input_data.kind or input_data.analysis.triage.kind
        body = (
            "w odpowiedzi na wniosek o udostępnienie informacji publicznej w zakresie liczby uczniów w szkołach "
            "podstawowych, na podstawie informacji przygotowanych przez komórkę merytoryczną, tj. Wydział Edukacji "
            "i Sportu Urzędu Miasta Bydgoszczy, uprzejmie informuję, że w roku szkolnym 2024/2025 do szkół "
            "podstawowych prowadzonych przez Miasto Bydgoszcz uczęszczało 21 437 uczniów, w tym 812 cudzoziemców."
        )
        text = Letter(
            case_number=input_data.case_number,
            addressee=input_data.analysis.applicant,
            body=body,
            letter_date=input_data.letter_date or date.today(),
        ).text()
        return DraftResult(
            kind=kind,
            letter_text=text,
            body=body,
            values_to_verify=["2024/2025", "21 437", "812", *placeholders(text)],
            notes="(mock) Sprawdź liczby z odpowiedzią wydziału.",
        )

    def delete_case(self, case_id: int) -> None:
        return None

    def health(self) -> Health:
        return Health(status="ok", vector_db_count=10, departments_loaded=29, llm_provider="mock")
