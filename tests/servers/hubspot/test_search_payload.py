import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'src'))
from servers.hubspot.main import build_tickets_search_payload

def test_pipeline_id_filter():
    result = build_tickets_search_payload({'pipeline_id': '0', 'limit': 50})
    expected = {'limit': 50, 'properties': [], 'filterGroups': [{'filters': [{'propertyName': 'hs_pipeline', 'operator': 'EQ', 'value': '0'}]}]}
    assert result == expected, f"Mismatch: {result}"
    print("PASS: pipeline_id filter")

def test_stage_id_filter():
    result = build_tickets_search_payload({'stage_id': '1', 'limit': 10})
    expected = {'limit': 10, 'properties': [], 'filterGroups': [{'filters': [{'propertyName': 'hs_pipeline_stage', 'operator': 'EQ', 'value': '1'}]}]}
    assert result == expected, f"Mismatch: {result}"
    print("PASS: stage_id filter")

def test_combined_filters():
    result = build_tickets_search_payload({'pipeline_id': '0', 'stage_id': '1', 'owner_id': '12345', 'limit': 100})
    assert result['filterGroups'][0]['filters'] == [
        {'propertyName': 'hs_pipeline', 'operator': 'EQ', 'value': '0'},
        {'propertyName': 'hs_pipeline_stage', 'operator': 'EQ', 'value': '1'},
        {'propertyName': 'hubspot_owner_id', 'operator': 'EQ', 'value': '12345'}
    ]
    print("PASS: combined filters")

def test_query_and_filters():
    result = build_tickets_search_payload({'pipeline_id': '0', 'query': 'urgent', 'limit': 50})
    assert result['query'] == 'urgent'
    assert 'filterGroups' in result
    print("PASS: query with filters")

def test_no_filters():
    result = build_tickets_search_payload({'limit': 10})
    assert 'filterGroups' not in result
    assert 'query' not in result
    print("PASS: no filters")

def test_after():
    result = build_tickets_search_payload({'after': 'abc123', 'limit': 50})
    assert result['after'] == 'abc123'
    print("PASS: after cursor")

def test_properties():
    result = build_tickets_search_payload({'properties': ['subject', 'content'], 'pipeline_id': '0', 'limit': 50})
    assert result['properties'] == ['subject', 'content']
    print("PASS: properties passthrough")

if __name__ == '__main__':
    test_pipeline_id_filter()
    test_stage_id_filter()
    test_combined_filters()
    test_query_and_filters()
    test_no_filters()
    test_after()
    test_properties()
    print("\nAll tests passed!")
