"""Original double refusal and a live, single-dispatch Main capability.

JSON artifacts are evidence only. Neither a saved review nor a constructed
assessment can recreate the process-local issuer or the original live job.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.desktop_review.external_mapping import canonical_json_bytes
from app.judgment.service import decision_profile_sha256

_ISSUER = object()


def digest(value):
    return sha256(canonical_json_bytes(value)).hexdigest()


def authenticated_refusal(service, assessment):
    try:
        raw = assessment['judgment']['judgment_result']
        ordinary = raw['ordinary_review']
        return (assessment['scope'] == 'candidate' and assessment['disposition'] == 'review'
            and assessment['authorizes_action'] is False
            and raw['status'] == 'completed' and raw['adopted'] is False
            and raw['disposition'] == 'review_required'
            and raw['choice_result']['choice'] in {'condition_not_met', 'evidence_insufficient'}
            and ordinary['status'] == 'completed'
            and ordinary['review_result']['choice'] in {'condition_not_met', 'evidence_insufficient'}
            and service.validate_result(raw, **assessment['evaluation_request']) is True)
    except (KeyError, TypeError, ValueError, OSError):
        return False


class PreActionSource:
    def __init__(self, issuer, *, target, scope, identity, rect):
        if issuer is not _ISSUER:
            raise ValueError('pre_action_source_issuer_invalid')
        from .action_review import _validate_result_binding
        if (not authenticated_refusal(scope['service'], scope['assessment'])
                or not _validate_result_binding(scope['service'], scope['assessment'],
                    envelope=scope['envelope'], cancelled=scope['cancelled'], require_pass=False)
                or target.input_claimed):
            raise ValueError('pre_action_source_not_authenticated')
        self.target, self.service, self.issuer = target, scope['service'], issuer
        self.context = deepcopy(scope['context'])
        self.envelope, self.assessment = deepcopy(scope['envelope']), deepcopy(scope['assessment'])
        self.identity, self.rect = deepcopy(identity), list(rect)
        self.target_digest = digest([target._state, target._candidate.model_dump()])
        self.binding_digest = digest([self.context, self.envelope, self.assessment, self.identity, self.rect])

    def validate(self):
        if (self.issuer is not _ISSUER
                or self.target_digest != digest([self.target._state, self.target._candidate.model_dump()])
                or self.binding_digest != digest([self.context, self.envelope, self.assessment, self.identity, self.rect])
                or decision_profile_sha256(self.service.profile) != self.envelope['profile_sha256']
                or not authenticated_refusal(self.service, self.assessment)):
            raise ValueError('pre_action_original_binding_invalid')
        frame = self.envelope['frame']
        if sha256(Path(frame['image_path']).read_bytes()).hexdigest() != frame['sha256']:
            raise ValueError('pre_action_original_image_changed')
        return True


def offer_source(target, scope, *, identity, rect):
    """Called only in the native candidate boundary, before input is claimed."""
    from app.core.agent_grounding_target import AgentGroundingTarget, current_agent_grounding
    if (type(target) is AgentGroundingTarget and current_agent_grounding() is target
            and target._pre_action_source is None and authenticated_refusal(scope['service'], scope['assessment'])):
        target._pre_action_source = PreActionSource(_ISSUER, target=target, scope=scope, identity=identity, rect=rect)


class MainPreActionApproval:
    def __init__(self, issuer, *, source, packet, review, validator, deadline_ns):
        if issuer is not _ISSUER or type(source) is not PreActionSource or not callable(validator):
            raise ValueError('main_pre_action_issuer_invalid')
        self._issuer, self.source, self._validator = issuer, source, validator
        self.packet, self.review = deepcopy(packet), deepcopy(review)
        self.deadline_ns, self._consumed = deadline_ns, False
        self.issued_ns = perf_counter_ns()
        fields = {'action', 'run_id', 'step_id', 'execution_request_id', 'verdict', 'reason',
            'evidence_sha256', 'review_packet_sha256', 'evidence_set_sha256', 'assessment_round'}
        if (type(deadline_ns) is not int or not self.issued_ns < deadline_ns <= self.issued_ns+60_000_000_000
                or type(review) is not dict or set(review) != fields or review['action'] != 'review'
                or review['verdict'] != 'success' or type(review['reason']) is not str
                or not review['reason'].strip() or len(review['reason']) > 4000
                or packet['schema'] != 'pre_action_review_packet.v1' or packet['stage'] != 'before_dispatch'
                or packet['packet_sha256'] != digest({k: v for k, v in packet.items() if k != 'packet_sha256'})
                or packet['envelope'] != source.envelope or packet['assessment'] != source.assessment
                or packet['before'] != source.envelope['frame']
                or any(packet[key] != source.context[key] for key in ('run_id', 'step_id', 'attempt_id'))
                or any(review[key] != packet[key] for key in ('run_id', 'step_id', 'execution_request_id',
                    'assessment_round', 'evidence_set_sha256'))
                or review['evidence_sha256'] != packet['before']['sha256']
                or review['review_packet_sha256'] != packet['packet_sha256']):
            raise ValueError('main_pre_action_approval_binding_invalid')
        self._binding = digest([self.packet, self.review, self.deadline_ns, self.issued_ns])
        self.validate()

    def validate(self):
        if (self._issuer is not _ISSUER or self._binding != digest([self.packet, self.review, self.deadline_ns, self.issued_ns])
                or perf_counter_ns() >= self.deadline_ns or self._validator() is not True
                or self.review['verdict'] != 'success' or self.source.validate() is not True):
            raise ValueError('main_pre_action_no_longer_valid')
        return True

    def consume(self):
        self.validate()
        if self._consumed:
            raise ValueError('main_pre_action_already_consumed')
        self._consumed = True

    def to_reference(self):
        self.validate()
        return {'schema': 'main_pre_action_adoption.v1', 'source': 'main_agent',
            'packet_sha256': self.packet['packet_sha256'], 'review': deepcopy(self.review),
            'original_envelope_sha256': self.source.envelope['envelope_sha256'],
            'original_assessment_sha256': digest(self.source.assessment),
            'deadline_ns': self.deadline_ns, 'artifact_is_authorization': False,
            'original_model_disposition': self.source.assessment['disposition']}


def _issue_main_pre_action_approval(**kwargs):
    return MainPreActionApproval(_ISSUER, **kwargs)
