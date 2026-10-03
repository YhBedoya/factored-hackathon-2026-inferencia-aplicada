import json

from eval.harness import pii_check

PERSONA = {
    "document_number": "DOC-TF0000001",
    "email": "prueba.uno@example.com",
    "phone": "+525511112222",
    "first_name": "Prueba",
    "last_name": "Uno",
}


def test_planted_document_number_found(tmp_path, monkeypatch, capsys):
    run = tmp_path / "r1"
    run.mkdir()
    rows = [
        {"id": "a", "input_text": "mi documento es ⟨DOC_1⟩"},
        {"id": "b", "input_text": "mi documento es doc-tf0000001 gracias"},
    ]
    (run / "llm_calls.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (run / "results.jsonl").write_text(json.dumps({"persona": "CLI-TFMULTI00001"}))
    monkeypatch.setattr(pii_check, "REPORTS", tmp_path)
    monkeypatch.setattr(pii_check, "_load_personas_pii", lambda ids: [PERSONA])

    code = pii_check.main(["--run", "r1"])

    out = capsys.readouterr().out
    assert code == 1
    assert "b KNOWN_DOC" in out and "1 hits" in out
    assert "TF0000001" not in out.upper()
