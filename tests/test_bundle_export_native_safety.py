"""World-space export must preserve the native game's bind-pose contract."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy

import fix_sifas_bundle_export as normalizer
from viewer_scene_fixture import bundle_fixture


def fixture(*, scale=1.0, translation=.7):
    environment=UnityPy.load(bundle_fixture(platform=9,unit_breast=True))
    # The general editing fixture deliberately contains body-scale edits.
    # Start this native-contract fixture from a rigid unit-scale skeleton.
    for obj in environment.objects:
        if obj.type.name=='Transform':
            tree=obj.read_typetree();tree['m_LocalScale']={key:1. for key in 'xyz'};obj.save_typetree(tree)
    environment=UnityPy.load(environment.file.save())
    worlds,objects=normalizer._bone_worlds(environment)
    for obj in environment.objects:
        if obj.type.name!='SkinnedMeshRenderer':continue
        renderer=obj.read_typetree();mesh=objects[renderer['m_Mesh']['m_PathID']];tree=mesh.read_typetree()
        for pose,bone in zip(tree['m_BindPose'],renderer['m_Bones']):
            transform=objects[bone['m_PathID']].read_typetree()
            name=objects[transform['m_GameObject']['m_PathID']].read().m_Name
            normalizer._mat_to_bindpose(np.linalg.inv(worlds[name]),pose)
        mesh.save_typetree(tree)
    environment=UnityPy.load(environment.file.save())
    root=next(o for o in environment.objects if o.type.name=='Transform'
        and o.read_typetree()['m_Father']['m_PathID']==0)
    tree=root.read_typetree()
    tree['m_LocalPosition']['y']+=translation
    tree['m_LocalScale']={key:scale for key in 'xyz'}
    root.save_typetree(tree)
    return environment.file.save()


class BundleExportNativeSafetyTests(unittest.TestCase):
    def test_unit_rigid_translation_normalizes_and_keeps_native_bindposes_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'original.unity',Path(folder)/'normalized.unity'
            raw=fixture();source.write_bytes(raw);report={}
            self.assertGreater(normalizer.normalize(source,target,False,report=report),0)
            self.assertTrue(report['changed']);self.assertEqual(report['skipped'],[])
            self.assertTrue(normalizer.validate(source,target,False))
            self.assertEqual(source.read_bytes(),raw)
            env=UnityPy.load(target.read_bytes())
            self.assertEqual({int(a.target_platform) for a in env.assets},{9})
            for obj in env.objects:
                if obj.type.name=='Mesh':self.assertIsNone(normalizer._native_bindpose_issue(obj.read_typetree()['m_BindPose']))

    def test_scaled_root_is_skipped_with_specific_reason_and_exact_original_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'scaled.unity',Path(folder)/'unchanged.unity'
            raw=fixture(scale=.99838);source.write_bytes(raw);report={}
            self.assertEqual(normalizer.normalize(source,target,False,report=report),0)
            self.assertFalse(report['changed']);self.assertTrue(report['skipped'])
            self.assertIn('scale',report['skipped'][0]['reason'])
            self.assertIn('unit bind-pose',report['skipped'][0]['reason'])
            self.assertTrue(report['skipped'][0]['mesh'])
            self.assertEqual(target.read_bytes(),raw);self.assertEqual(source.read_bytes(),raw)
            self.assertTrue(normalizer.validate(source,target,False))

    def test_shear_reflection_and_native_squared_column_rule_are_specific(self):
        shear=np.eye(4);shear[0,1]=.04
        reflection=np.diag([-1.,1,1,1])
        self.assertIn('shear',normalizer._mesh_root_issue(shear))
        self.assertIn('reflection',normalizer._mesh_root_issue(reflection))
        pose={f'e{r}{c}':float(r==c) for r in range(4) for c in range(4)}
        pose['e00']=1.001623
        issue=normalizer._native_bindpose_issue([pose])
        self.assertIn('bind pose 0, column 0',issue);self.assertIn('squared length',issue)
        # Norm≈1.0000007 would pass an incorrect magnitude-only check, while
        # native squared magnitude≈1.0000014 must be rejected.
        pose['e00']=1.0000007
        self.assertIsNotNone(normalizer._native_bindpose_issue([pose]))

    def test_invalid_original_bindpose_is_not_rewritten_or_claimed_fixed(self):
        env=UnityPy.load(fixture());mesh=next(o for o in env.objects if o.type.name=='Mesh')
        tree=mesh.read_typetree();tree['m_BindPose'][0]['e00']=2.;mesh.save_typetree(tree);raw=env.file.save()
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'invalid.unity',Path(folder)/'unchanged.unity'
            source.write_bytes(raw);report={}
            self.assertEqual(normalizer.normalize(source,target,False,report=report),0)
            self.assertIn('original mesh already fails native binding',report['skipped'][0]['reason'])
            self.assertEqual(target.read_bytes(),raw)

    def test_failed_atomic_publication_preserves_existing_output_and_original(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'original.unity',Path(folder)/'existing.unity'
            raw=fixture();source.write_bytes(raw);target.write_bytes(b'previous user result')
            with patch.object(normalizer.os,'replace',side_effect=OSError('simulated unavailable output')):
                with self.assertRaises(OSError):normalizer.normalize(source,target,False)
            self.assertEqual(source.read_bytes(),raw);self.assertEqual(target.read_bytes(),b'previous user result')
            self.assertEqual(list(Path(folder).glob('.sifas-normalize-*')),[])

    def test_app_adapter_exposes_specific_skip_and_no_change_instead_of_success(self):
        spec=importlib.util.spec_from_file_location('native_safe_mesh_adapter',
            Path(normalizer.__file__).parent/'webtools/tools/mesh.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        class Job:
            def __init__(self):self.logs=[]
            def log(self,line):self.logs.append(line)
            def progress(self,*args):pass
        def skipped(*args,report,**kwargs):
            report.update(fixed=0,changed=False,skipped=[{'mesh':'Masked Face','reason':'mesh-root scale 0.998 violates unit bind-pose columns'}])
            return 0
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.unity';source.write_bytes(b'original source');job=Job()
            with patch.object(adapter,'ensure_repo_on_path'),patch.object(normalizer,'normalize',side_effect=skipped),patch.object(normalizer,'validate',return_value=True):
                result=adapter.run_fix_export(job,{'in_path':str(source),'out_dir':folder})
            self.assertIn('SKIPPED',result);self.assertIn('copied unchanged',result)
            self.assertTrue(any('Masked Face' in line and 'scale 0.998' in line for line in job.logs))
            self.assertFalse(any(line.startswith('OK ') for line in job.logs))


if __name__=='__main__':unittest.main()
