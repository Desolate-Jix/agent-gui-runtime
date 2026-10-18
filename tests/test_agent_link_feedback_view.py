import base64
from io import BytesIO
from PIL import Image
from app.agent_link.feedback_view import compact_feedback_view
def test_compacts_without_mutation():
 b=BytesIO();Image.new("RGB",(1,1)).save(b,format="PNG"); raw=base64.b64encode(b.getvalue()).decode()
 original={"issues":[{"review_baseline_sha256":"a"*64,"review_baseline":{"contract_version":"desktop_review_baseline_v1","task_id":"t","workspace_revision":1,"source_ref":"b"*64,"batch_sha256":"c"*64,"batch":{"screenshots":[{"screenshot_id":"s","png_base64":raw}],"interfaces":[{"meaning":"purpose","recognition_text":"title","regions":[]}],"steps":[]}}}]}
 result=compact_feedback_view(original); assert "review_baseline" in original["issues"][0]; issue=result["issues"][0]; assert "review_baseline" not in issue; view=issue["review_baseline_view"]; assert view["source_baseline_sha256"]=="a"*64 and view["batch"]["interfaces"][0]["recognition_text"]=="title"; assert "png_base64" not in view["batch"]["screenshots"][0] and view["batch"]["screenshots"][0]["inline_image_omitted"]
