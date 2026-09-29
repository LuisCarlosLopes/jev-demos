from sprint_radar import model


def test_calendar_and_capacity(snapshot):
    sp = snapshot["sprint"]
    assert (sp["business_days"], sp["days_elapsed"], sp["days_left"]) == (10, 7, 4)
    people = {p["name"]: p for p in snapshot["people"]}
    assert people["Ana"]["remaining_capacity_h"] == 24
    assert people["Luis"]["remaining_capacity_h"] == 0
    assert people["Luis"]["days_off_in_window"] == 4
    assert people["Luis"]["load_ratio"] is None
    assert people["Ana"]["remaining_h"] == 10
    assert people["Ana"]["load_ratio"] == 0.42


def test_totals_exclude_removed_and_containers(snapshot):
    t = snapshot["totals"]
    assert t["scope_h"] == 25  # 6+4+2+10+3; a Removed (1h) fica fora
    assert t["closed_h"] == 2
    assert t["remaining_h"] == 23
    assert t["unassigned_h"] == 3
    assert t["open_tasks"] == 4
    assert t["capacity_h"] == 24


def test_stream_inheritance_and_text_cleanup(snapshot):
    nodes = snapshot["nodes"]
    assert nodes[100]["stream"] == "Stream B" and nodes[100]["stream_inherited"]
    assert nodes[110]["stream"] == "Stream A"
    assert nodes[100]["description"] == "Revisar & documentar"
    assert nodes[100]["days_since_activated"] == 1
    assert nodes[102]["remaining_h"] == 0
    assert snapshot["roots"] == [1]


def test_attach_comments_strips_html_and_empty():
    snap = {"nodes": {5: {"comments": []}}}
    model.attach_comments(
        snap,
        {
            5: [
                {"author": "M", "date": "2026-09-29T12:00:00Z", "text": "<b>PR</b> mergeado"},
                {"author": "M", "date": "2026-09-28T12:00:00Z", "text": "<div></div>"},
            ]
        },
    )
    assert snap["nodes"][5]["comments"] == [
        {"author": "M", "date": "2026-09-29", "text": "PR mergeado"}
    ]


def test_rollup_weights_by_remaining_hours(snapshot):
    results = {
        100: {"will_close": 0.9},
        101: {"will_close": 0.2},
        110: {"will_close": 0.1},
        111: {"will_close": 0.5},
    }
    agg = model.rollup(snapshot, results)
    us = agg[10]
    assert us["tasks"] == 2 and us["at_risk"] == 1
    assert us["p"] == round((0.9 * 6 + 0.2 * 4) / 10, 3)
    feature = agg[1]
    assert feature["tasks"] == 4
    assert 0 < feature["p"] < 1
