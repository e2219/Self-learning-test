import json
import httpx


def review_response(request):
    task = json.loads(json.loads(request.content)['messages'][1]['content'])
    if task.get('stage') == 'blind_review':
        payload = {'answer': 'A', 'option_judgments': [{'label': c, 'verdict': 'correct' if c == 'A' else 'incorrect', 'reason': '测试资料依据'} for c in 'ABCD'] if task['type'] == 'choice' else [],
                   'type_matches': True, 'supported': True, 'unambiguous': True, 'duplicate': False, 'issues': []}
    elif task.get('stage') == 'consistency_review':
        payload = {'answer_matches': True, 'explanation_consistent': True, 'evidence_supported': True, 'issues': []}
    else:
        return None
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload)}}], 'usage': {'total_tokens': 0}})
