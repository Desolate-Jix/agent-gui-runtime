"""视觉能力准入的派发前拒绝事实，执行和只读核验共用同一合同。"""
from copy import deepcopy
from hashlib import sha256
from app.desktop_review.external_mapping import canonical_json_bytes

class AgentCommandError(ValueError):
    pass


class AgentCommandVisionAdmissionError(AgentCommandError):
    """仅在能力路由判定后、创建 worker 和派发前提供零输入事实。"""

    def __init__(self, command_id, command, configuration, capabilities, reason):
        super().__init__(reason)
        self.command_id = command_id
        self.command = deepcopy(command)
        self.configuration = configuration.model_dump()
        self.capabilities = capabilities.model_dump()

    def before_dispatch_result(self, command_id):
        if command_id != self.command_id:
            raise ValueError('vision_admission_command_id_mismatch')
        return {'contract_version': 'vision_admission_rejection.v1',
                'command_id': command_id, 'command_sha256': sha256(canonical_json_bytes(self.command)).hexdigest(),
                'status': 'rejected_before_dispatch', 'phase': 'before_worker_creation',
                'reason': str(self), 'configuration': deepcopy(self.configuration),
                'capabilities': deepcopy(self.capabilities),
                'input_attempted': False, 'action_executed': False}
