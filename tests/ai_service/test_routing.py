from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_service.routing import Department, DepartmentDirectory, DepartmentRouter, ExternalBody, ExternalBodyDirectory

models.ALLOW_MODEL_REQUESTS = False

DIRECTORY = DepartmentDirectory(
    [
        Department(id=1, code="WE", name="Wydział Edukacji i Sportu", responsibilities="oświata, szkoły"),
        Department(id=2, code="WGO", name="Wydział Gospodarki Odpadami", responsibilities="odpady komunalne"),
    ]
)
QUESTIONS = ["Liczba uczniów w szkołach podstawowych.", "Liczba mieszkańców według opłat za odpady."]


def _model(*responses: dict) -> tuple[FunctionModel, list[str]]:
    """FunctionModel returning the given outputs in order; records prompts it received."""
    calls: list[str] = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(str(messages[-1]))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, responses[len(calls) - 1])])

    return FunctionModel(fn), calls


def test_routes_each_question_and_keeps_original_text():
    model, calls = _model(
        {"routes": [{"question_index": 0, "departments": ["WE"]}, {"question_index": 1, "departments": ["WGO"]}]}
    )
    result = DepartmentRouter(model, DIRECTORY).route(QUESTIONS)
    assert [(q.question, q.departments) for q in result.questions] == [(QUESTIONS[0], ["WE"]), (QUESTIONS[1], ["WGO"])]
    assert result.all_departments() == ["WE", "WGO"]
    assert "[WE] Wydział Edukacji i Sportu" in calls[0] and "0. Liczba uczniów" in calls[0]


def test_unknown_code_triggers_retry():
    model, calls = _model(
        {"routes": [{"question_index": 0, "departments": ["XYZ"]}, {"question_index": 1, "departments": []}]},
        {"routes": [{"question_index": 0, "departments": ["WE"]}, {"question_index": 1, "departments": []}]},
    )
    result = DepartmentRouter(model, DIRECTORY).route(QUESTIONS)
    assert len(calls) == 2 and "Unknown unit codes ['XYZ']" in calls[1]
    assert result.questions[0].departments == ["WE"] and result.questions[1].departments == []


def test_missing_question_triggers_retry():
    model, calls = _model(
        {"routes": [{"question_index": 0, "departments": ["WE"]}]},
        {"routes": [{"question_index": 0, "departments": ["WE"]}, {"question_index": 1, "departments": ["WGO"]}]},
    )
    result = DepartmentRouter(model, DIRECTORY).route(QUESTIONS)
    assert len(calls) == 2
    assert result.all_departments() == ["WE", "WGO"]


def test_without_llm_returns_empty_suggestions():
    result = DepartmentRouter(None, DIRECTORY).route(QUESTIONS + ["  "])
    assert [q.departments for q in result.questions] == [[], []]


def test_real_directory_loads_with_unique_codes():
    directory = DepartmentDirectory.load()
    codes = [d.code for d in directory.departments]
    assert len(codes) >= 20 and len(codes) == len(set(codes))
    assert all(d.responsibilities for d in directory.departments)


BODIES = ExternalBodyDirectory(
    [ExternalBody(id="zdmikp", name="Zarząd Dróg Miejskich i Komunikacji Publicznej", kind="budget_unit")]
)


def test_external_body_when_no_department_and_bodies_in_prompt():
    model, calls = _model(
        {
            "routes": [
                {"question_index": 0, "departments": ["WE"], "external_body": "zdmikp"},  # ignored: has a department
                {"question_index": 1, "departments": [], "external_body": "zdmikp"},
            ]
        }
    )
    result = DepartmentRouter(model, DIRECTORY, BODIES).route(QUESTIONS)
    assert [(q.departments, q.external_body) for q in result.questions] == [(["WE"], None), ([], "zdmikp")]
    assert result.competent_body() == "zdmikp"
    assert "[zdmikp] Zarząd Dróg Miejskich i Komunikacji Publicznej (jednostka budżetowa)" in calls[0]


def test_unknown_external_body_triggers_retry():
    model, calls = _model(
        {"routes": [{"question_index": 0, "departments": [], "external_body": "policja"},
                    {"question_index": 1, "departments": ["WGO"]}]},
        {"routes": [{"question_index": 0, "departments": [], "external_body": None},
                    {"question_index": 1, "departments": ["WGO"]}]},
    )
    result = DepartmentRouter(model, DIRECTORY, BODIES).route(QUESTIONS)
    assert len(calls) == 2 and result.questions[0].external_body is None and result.competent_body() is None


def test_committed_external_bodies_load():
    bodies = ExternalBodyDirectory.load()
    assert len(bodies.bodies) >= 30
    zdmikp = next(b for b in bodies.bodies if b.name.startswith("Zarząd Dróg Miejskich"))
    assert zdmikp.email == "zarzad@zdmikp.bydgoszcz.pl" and "Toruńska 174A" in zdmikp.address
