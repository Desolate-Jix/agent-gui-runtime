from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.desktop_review.model_setup_dialog import ModelSetupDialog
class C:
 def __init__(self):self.calls=[];self.exists=False
 def model_setup_status(self):return {'config_path':'C:/x/vision.json','config_exists':self.exists,'default_port':13244}
 def configure_vista_model(self,**kw):self.calls.append(kw);return {'status':'configured_unverified'}
def test_explicit_save_only_and_exact_args(monkeypatch):
 app=QApplication.instance() or QApplication([]);c=C();d=ModelSetupDialog(c);d.path.setText('C:/models/vista');d.port.setValue(14567);assert c.calls==[];d._save();
 for _ in range(100):
  if d._job is None: break
  QTest.qWait(10)
 assert d._job is None
 assert c.calls==[{'model_directory':'C:/models/vista','port':14567}]
def test_existing_config_refuses_save():
 app=QApplication.instance() or QApplication([]);c=C();c.exists=True;d=ModelSetupDialog(c);assert not d.save.isEnabled()
