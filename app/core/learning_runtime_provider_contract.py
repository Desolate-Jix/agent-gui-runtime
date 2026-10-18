"""明确的学习提供者接口；不实现准备、动作或宿主生命周期。"""
from abc import ABC, abstractmethod


class LearningRuntimeProviderContract(ABC):
    owner: object

    @classmethod
    def register(cls, subclass):
        # 不允许虚拟注册跳过真实继承和抽象能力实现。
        raise TypeError("learning_runtime_provider_virtual_subclass_forbidden")

    @abstractmethod
    def prepare(self, *, connection_id, task_id, segment_id, idempotency_key, asset_id, asset_content_sha256, target_window_handle, target_process_id) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get(self, *, connection_id, task_id, segment_id, preparation_id) -> dict:
        raise NotImplementedError

    @abstractmethod
    def cancel_reviewed(self, *, connection_id, task_id, segment_id, preparation_id):
        raise NotImplementedError

    @abstractmethod
    def request_reviewed_action(self, *, connection_id, task_id, segment_id, preparation_id, intent_id, action_id, text_values=None) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_reviewed_action_result(self, *, connection_id, task_id, segment_id, preparation_id) -> dict:
        raise NotImplementedError

    @abstractmethod
    def prepare_fresh(self, *, connection_id, task_id, segment_id, batch_id, idempotency_key):
        raise NotImplementedError

    @abstractmethod
    def request_fresh(self, *, connection_id, task_id, segment_id, preparation_id, intent_id, action_id, semantic_action, goal, text_parameters=None, text_values=None, learned_control=None, scroll_parameters=None):
        raise NotImplementedError

    @abstractmethod
    def get_fresh(self, *, connection_id, task_id, segment_id, preparation_id):
        raise NotImplementedError

    @abstractmethod
    def cancel_fresh(self, *, connection_id, task_id, segment_id, preparation_id):
        raise NotImplementedError
