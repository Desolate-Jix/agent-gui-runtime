"""细长表单控件不能因限长缩图而丢失文字和点击高度。"""
import pytest
from PIL import Image
from app.api import vision
from app.vision.schemas import ImageSize
from app.core.runtime_artifacts import pinned_runtime_output_root
from tests.test_selection_control_roi_context import candidate

@pytest.mark.parametrize('role,width,height',[('listitem',810,28),('input',751,17),('combobox',827,33)])
def test_wide_thin_current_form_keeps_real_pixels(tmp_path,role,width,height):
    path=tmp_path/'wide.png'
    Image.new('RGB',(2560,1400),'white').save(path)
    box={'x':500,'y':500,'w':width,'h':height}
    item=candidate(role,'Choice',box)
    with pinned_runtime_output_root(tmp_path):
        r=vision._prepare_vista_candidate_roi_image(path,ImageSize(width=2560,height=1400),candidates=[item],max_edge=448,padding=12,min_size=96,roi_source='current_uia_candidate_v1')
    assert r['transform']['scale_original_to_processed']['y']>=1
    assert r['context_reason']=='wide_thin_form_control_pixels'
    assert r['processed_size']['width']<=2048
    assert r['pathgraph_candidates'][0]['bbox_original']==box
    assert r['transform']['scale_original_to_processed']['y']*r['transform']['scale_processed_to_original']['y']==pytest.approx(1)
