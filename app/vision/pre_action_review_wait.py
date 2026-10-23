"""Park the original job after the native owner has returned a proven zero input."""
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns

from app.core.instant_command_queue import CommandQueueBusy
from app.core.vision_admission_contract import AgentCommandCancelled, AgentCommandError
from app.execution.main_pre_action_approval import PreActionSource, digest, _issue_main_pre_action_approval
from .field_review_wait import _request_id, _record_view


class PreActionReviewWait:
    def _remember_pre_action_control(self, record, request_id):
        from app.core.json_snapshot import read_json_snapshot
        path = Path(self.store.session_root) / 'commands' / (request_id+'.json')
        if path.is_file():
            record['accepted_controls'][request_id] = digest(read_json_snapshot(path))

    def _pre_action_bound(self, job):
        validator = self.pre_action_plan_validator
        if not callable(validator):
            return False
        original_record = job.pre_action_review_state
        contended = False
        while True:
            if contended:
                record = job.pre_action_review_state
                deadline = record['deadline_ns'] if record else job.action_review_deadline_ns
                fresh = getattr(record['target'], '_main_fresh', None) if record else None
                if fresh is not None:
                    deadline = min(deadline, fresh['checked_ns'] + 2_000_000_000)
                if (self._closed or job.cancelled or self._jobs.get(job.command_id) is not job
                        or record is not original_record
                        or (Path(self.store.session_root) / 'closing.json').exists()
                        or perf_counter_ns() >= deadline):
                    job.pre_action_binding_failure = 'queue_busy_interrupted_or_expired'
                    return False
            try:
                return validator(job.command_id, deepcopy(job.action_review)) is True
            except CommandQueueBusy as error:
                if type(error) is not CommandQueueBusy:
                    raise
                # All callers own the job Condition. Release it during a short
                # wait so the queue owner can finish admission/cancel; never
                # treat contention as a successful binding or renew a lease.
                contended = True
                record = job.pre_action_review_state
                deadline = record['deadline_ns'] if record else job.action_review_deadline_ns
                fresh = getattr(record['target'], '_main_fresh', None) if record else None
                if fresh is not None:
                    deadline = min(deadline, fresh['checked_ns'] + 2_000_000_000)
                if (self._closed or job.cancelled or self._jobs.get(job.command_id) is not job
                        or (Path(self.store.session_root) / 'closing.json').exists()
                        or perf_counter_ns() >= deadline):
                    job.pre_action_binding_failure = 'queue_busy_interrupted_or_expired'
                    return False
                self._condition.wait(timeout=min(.01, max(0, (deadline-perf_counter_ns())/1e9)))

    def _pre_action_checked(self, job, record):
        reason = ('host_closed' if self._closed else 'cancelled' if job.cancelled else
            'job_owner_changed' if self._jobs.get(job.command_id) is not job else
            'review_record_changed' if job.pre_action_review_state is not record else
            'session_closing' if (Path(self.store.session_root) / 'closing.json').exists() else
            'main_deadline_expired' if perf_counter_ns() >= record['deadline_ns'] else None)
        if reason is None and not self._pre_action_bound(job):
            reason = 'plan_binding:' + str(getattr(job, 'pre_action_binding_failure', None) or 'validator_rejected')
        if reason is not None:
            raise AgentCommandError('pre_action_review_no_longer_active:' + reason)
        packet = record['packet']
        if (packet['packet_sha256'] != digest({k: v for k, v in packet.items() if k != 'packet_sha256'})
                or packet['evidence_set_sha256'] != digest(packet['evidence_refs'])
                or self._snapshots[job.command_id].get('pre_action_review') != _record_view(record)
                or digest(record['receipt']) != packet['original_receipt_sha256']
                or record['source'].validate() is not True or record['target'].input_claimed):
            raise AgentCommandError('pre_action_review_original_binding_invalid')
        for reference in packet['evidence_refs']:
            if self._field_reference(Path(self.store.session_root) / reference['path']) != reference:
                raise AgentCommandError('pre_action_review_evidence_changed')
        return True

    def _await_pre_action_review(self, job, target, receipt, attempt_index):
        from app.core.recognition_dispatch import local_receipt_zero_input_verified
        source = target._pre_action_source
        # No partial/previous input, no unknown queue, no provider/protocol error.
        with self._condition:
            state = self._snapshots[job.command_id]
            if (type(source) is not PreActionSource or source.target is not target or target.input_claimed
                    or job.pre_action_review_state is not None or job.action_review != source.context
                    or state['action_executed'] is not False or state['dispatch_in_progress'] is not False
                    or len(state['dispatch_attempts']) != 1 or attempt_index != 1
                    or receipt.get('local_input_scope_closed') is not True
                    or receipt.get('action_assessment') != source.assessment
                    or not local_receipt_zero_input_verified(receipt, 'execute_recognition_plan')
                    or not self._pre_action_bound(job)):
                return None
            source.validate()
            frame = source.envelope['frame']
            reference = self._field_reference(frame['image_path'])
            if reference['sha256'] != frame['sha256']:
                raise AgentCommandError('pre_action_review_image_changed')
            deadline = perf_counter_ns() + 300_000_000_000
            packet = {'schema': 'pre_action_review_packet.v1', 'stage': 'before_dispatch',
                'session_directory': str(Path(self.store.session_root).resolve()), 'owner_id': self.store.owner_id,
                'reason': 'authenticated_double_refusal', 'command_id': job.command_id,
                'execution_request_id': job.command_id, 'run_id': source.context['run_id'],
                'step_id': source.context['step_id'], 'attempt_id': source.context['attempt_id'],
                'plan_sha256': digest(source.context['plan']), 'assessment_round': 0,
                'target_identity': deepcopy(frame['window_identity']), 'window_rect': source.rect,
                'candidate': deepcopy(source.envelope['candidate']), 'before': deepcopy(frame),
                'envelope': deepcopy(source.envelope), 'assessment': deepcopy(source.assessment),
                'profile_sha256': source.envelope['profile_sha256'],
                'original_receipt_id': receipt['step_id'], 'original_receipt_sha256': digest(receipt),
                'evidence_refs': [reference], 'evidence_set_sha256': digest([reference]),
                'original_input_status': 'not_dispatched', 'action_executed': False,
                'main_wait_deadline_ns': deadline, 'authorizes_action': False, 'automatic_retry_allowed': False,
                'image': {'tool': 'instant_image', 'view': 'before',
                    'instruction': 'Use a NEW agent_command_status outer request_id for this command, then instant_image(request_id=that_status_id, view=before).'}}
            packet['packet_sha256'] = digest(packet)
            record = {'packet': packet, 'review': None, 'review_request_id': None, 'continued': False,
                'continue_request_id': None, 'requests': {}, 'deadline_ns': deadline,
                'accepted_controls': {},
                'source': source, 'target': target, 'receipt': deepcopy(receipt)}
            job.pre_action_review_state = record
            attempts = deepcopy(state['dispatch_attempts'])
            attempts[-1]['status'] = 'paused_before_input'
            self._update(job, status='awaiting_pre_action_review', pending_pre_action_review=packet,
                pre_action_review=_record_view(record), dispatch_attempts=attempts)
            self._condition.notify_all()
            while not record['continued'] and (record['review'] or {}).get('verdict') != 'failure':
                self._pre_action_checked(job, record)
                self._condition.wait(timeout=min(.1, max(0, (deadline-perf_counter_ns())/1e9)))
            self._pre_action_checked(job, record)
            if record['review']['verdict'] == 'failure':
                self._update(job, pre_action_resolution={'schema': 'pre_action_outcome.v1',
                    'status': 'stopped_before_input', 'reason': 'main_rejected', 'input_claimed': False})
                return None
        def live():
            with self._condition:
                # Claiming input is one-shot; later native validators may still read the adoption.
                claimed = target.input_claimed
                if claimed:
                    return (not self._closed and not job.cancelled and self._jobs.get(job.command_id) is job
                        and self._snapshots[job.command_id]['status'] == 'running'
                        and self._pre_action_bound(job))
                return (record['continued'] and self._snapshots[job.command_id]['status'] == 'running'
                    and self._pre_action_checked(job, record))
        return _issue_main_pre_action_approval(source=source, packet=packet, review=record['review'], validator=live,
            deadline_ns=job.action_review_deadline_ns)

    def get_pre_action_review(self, command_id):
        self._path(command_id)
        with self._condition:
            job = self._jobs.get(command_id)
            record = getattr(job, 'pre_action_review_state', None)
            if (record is None or self._snapshots[command_id]['status'] != 'awaiting_pre_action_review'
                    or record['continued'] or job.cancelled or self._closed):
                return None
            self._pre_action_checked(job, record)
            return _record_view(record)

    def review_pre_action(self, command_id, request_id, review):
        self._path(command_id)
        _request_id(request_id)
        with self._condition:
            job = self._jobs.get(command_id)
            record = getattr(job, 'pre_action_review_state', None)
            if record is None:
                raise AgentCommandError('pre_action_review_not_awaiting')
            claim = {'action': 'review', 'review': deepcopy(review)}
            prior = record['requests'].get(request_id)
            if prior is not None:
                if prior != claim:
                    raise AgentCommandError('pre_action_review_request_conflict')
                return _record_view(record)
            self._pre_action_checked(job, record)
            packet = record['packet']
            fields = {'action', 'run_id', 'step_id', 'execution_request_id', 'verdict', 'reason',
                'evidence_sha256', 'review_packet_sha256', 'evidence_set_sha256', 'assessment_round'}
            if (record['continued'] or self._snapshots[command_id]['status'] != 'awaiting_pre_action_review'
                    or type(review) is not dict or set(review) != fields or review['action'] != 'review'
                    or review['verdict'] not in {'success', 'failure'}
                    or type(review['reason']) is not str or not review['reason'].strip() or len(review['reason']) > 4000
                    or type(review['assessment_round']) is not int
                    or any(review[key] != packet[key] for key in ('run_id', 'step_id', 'execution_request_id',
                        'evidence_set_sha256', 'assessment_round'))
                    or review['evidence_sha256'] != packet['before']['sha256']
                    or review['review_packet_sha256'] != packet['packet_sha256']):
                raise AgentCommandError('pre_action_review_request_binding_invalid')
            if record['review'] is not None and record['review'] != review:
                raise AgentCommandError('pre_action_review_already_reviewed')
            record['requests'][request_id] = claim
            self._remember_pre_action_control(record, request_id)
            if record['review'] is None:
                record.update(review=deepcopy(review), review_request_id=request_id)
                self._update(job, pre_action_review=_record_view(record))
            self._condition.notify_all()
            return _record_view(record)

    def continue_pre_action(self, command_id, request_id):
        self._path(command_id)
        _request_id(request_id)
        with self._condition:
            job = self._jobs.get(command_id)
            record = getattr(job, 'pre_action_review_state', None)
            if record is None:
                raise AgentCommandError('pre_action_review_not_awaiting')
            claim = {'action': 'continue', 'packet_sha256': record['packet']['packet_sha256']}
            prior = record['requests'].get(request_id)
            if prior is not None:
                if prior != claim:
                    raise AgentCommandError('pre_action_review_request_conflict')
                return deepcopy(self._snapshots[command_id])
            self._pre_action_checked(job, record)
            if (record['continued'] or (record['review'] or {}).get('verdict') != 'success'
                    or self._snapshots[command_id]['status'] != 'awaiting_pre_action_review'):
                raise AgentCommandError('pre_action_review_success_required')
            record['requests'][request_id] = claim
            self._remember_pre_action_control(record, request_id)
            record.update(continued=True, continue_request_id=request_id)
            job.action_review_deadline_ns = perf_counter_ns() + min(job.action_review['budget_ms'], 60000)*1_000_000
            record['deadline_ns'] = job.action_review_deadline_ns
            result = self._update(job, status='running', pending_pre_action_review=None,
                pre_action_review=_record_view(record))
            self._condition.notify_all()
            return result
