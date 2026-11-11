"""Game-facing asset tools reuse UVs by default and relocate only by request."""
import unittest
import tempfile
from unittest.mock import patch

from webtools.jobs import Job
from webtools.tools import costume, registry


class ReuseEmptyUVToolTests(unittest.TestCase):
    def test_part_tool_has_one_uv_strategy_with_clear_defaults(self):
        fields = {field['name']: field for field in registry.get_tool('costume_part_transplant')['fields']}
        placement = fields['uv_placement']
        self.assertEqual(placement['type'], 'select')
        self.assertEqual(placement['default'], 'same_position')
        self.assertEqual([option['value'] for option in placement['options']],
                         ['same_position', 'move_to_empty', 'atlas'])
        for option in placement['options']:
            self.assertIn('No padding', option['help'])
        self.assertIn('keep the original UV positions', placement['options'][0]['help'])
        self.assertIn('Keep main-texture resolution', placement['options'][1]['help'])
        for legacy in ('reuse_empty_uv', 'relocate_empty_uv', 'upscale_textures_for_uv_reuse'):
            self.assertNotIn(legacy, fields)
        self.assertIs(fields['preserve_physics']['default'], True)
        self.assertIs(fields['restore_collision']['default'], True)

    def test_asset_tool_rejects_non_boolean_uv_reuse_before_loading_or_writing(self):
        for option in ('reuse_empty_uv', 'relocate_empty_uv', 'upscale_textures_for_uv_reuse'):
            for invalid in ('false', 0, 1, None, [], {}):
                with self.subTest(option=option, value=invalid), patch.object(costume, 'ensure_repo_on_path') as load:
                    with self.assertRaisesRegex(ValueError, 'true or false'):
                        costume.run_costume_part_transplant(Job('uv-option-validation', 'costume_part_transplant'),
                            {option: invalid})
                    load.assert_not_called()
        with patch.object(costume, 'ensure_repo_on_path') as load:
            with self.assertRaisesRegex(ValueError, 'Enable empty UV reuse'):
                costume.run_costume_part_transplant(Job('uv-option-validation', 'costume_part_transplant'),
                    {'reuse_empty_uv': False, 'relocate_empty_uv': True})
            load.assert_not_called()

    def test_asset_tool_forwards_default_and_explicit_texture_matching_choice(self):
        import costume_part_transplant as part
        for supplied, expected in (({}, True), ({"upscale_textures_for_uv_reuse": False}, False),
                                   ({"reuse_empty_uv": False}, True)):
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as directory, \
                    patch("webtools.tools.texture.ensure_astc_cli"), \
                    patch.object(costume, "ensure_repo_on_path"), \
                    patch.object(costume, "_match_to_target"), \
                    patch.object(part, "transplant_part") as transplant:
                costume.run_costume_part_transplant(Job("uv-match-forwarding", "costume_part_transplant"),
                    {"donor": "donor.unity", "target": "target.unity", "out_dir": directory, **supplied})
                self.assertIs(transplant.call_args.kwargs["upscale_textures_for_uv_reuse"], expected)

    def test_asset_tool_uv_strategy_is_strict_and_overrides_legacy_combinations(self):
        import costume_part_transplant as part
        for invalid in ('', 'unknown', None, False, 0, 1, [], {}):
            with self.subTest(invalid=invalid), patch.object(costume, 'ensure_repo_on_path') as load:
                with self.assertRaisesRegex(ValueError, 'UV placement'):
                    costume.run_costume_part_transplant(Job('uv-placement-invalid', 'costume_part_transplant'),
                        {'uv_placement': invalid})
                load.assert_not_called()
        for placement in ('same_position', 'move_to_empty', 'atlas'):
            with self.subTest(placement=placement), tempfile.TemporaryDirectory() as directory, \
                    patch('webtools.tools.texture.ensure_astc_cli'), \
                    patch.object(costume, 'ensure_repo_on_path'), \
                    patch.object(costume, '_match_to_target'), \
                    patch.object(part, 'transplant_part') as transplant:
                costume.run_costume_part_transplant(Job('uv-placement-forward', 'costume_part_transplant'),
                    {'donor': 'donor.unity', 'target': 'target.unity', 'out_dir': directory,
                     'uv_placement': placement, 'reuse_empty_uv': False, 'relocate_empty_uv': True})
                self.assertEqual(transplant.call_args.kwargs['uv_placement'], placement)

    def test_cli_explicit_uv_strategy_overrides_legacy_flags(self):
        import costume_part_transplant as part
        base = ['transplant', '--donor', 'donor.unity', '--target', 'target.unity',
                '--out', 'output.unity', '--auto', '--dry-run',
                '--no-reuse-empty-uv', '--relocate-empty-uv']
        for placement in ('same_position', 'move_to_empty', 'atlas'):
            with self.subTest(placement=placement), patch.object(part, 'transplant_part') as transplant:
                args = part.build_parser().parse_args(base + ['--uv-placement', placement])
                self.assertEqual(part.run_cli(args), 0)
                self.assertEqual(transplant.call_args.kwargs['uv_placement'], placement)
        self.assertIsNone(part.build_parser().parse_args(base).uv_placement)

    def test_part_rejects_invalid_strategy_before_loading(self):
        import costume_part_transplant as part
        for invalid in ('', 'unknown', False, 0, 1, [], {}):
            with self.subTest(invalid=invalid), patch.object(part, '_require_unitypy') as load:
                with self.assertRaisesRegex(ValueError, 'UV placement'):
                    part.transplant_part('donor.unity', 'target.unity', 'output.unity', uv_placement=invalid)
                load.assert_not_called()

    def test_cli_texture_matching_defaults_on_and_can_be_disabled(self):
        import costume_part_transplant as part
        base = ["transplant", "--donor", "donor.unity", "--target", "target.unity",
                "--out", "output.unity", "--auto", "--dry-run"]
        for flags, expected in (([], True), (["--no-upscale-textures-for-uv-reuse"], False),
                                (["--no-upscale-textures-for-uv-reuse", "--upscale-textures-for-uv-reuse"], True)):
            with self.subTest(flags=flags), patch.object(part, "transplant_part") as transplant:
                args = part.build_parser().parse_args(base + flags)
                self.assertIs(args.upscale_textures_for_uv_reuse, expected)
                self.assertEqual(part.run_cli(args), 0)
                self.assertIs(transplant.call_args.kwargs["upscale_textures_for_uv_reuse"], expected)

    def test_part_function_rejects_invalid_uv_options_before_loading(self):
        import costume_part_transplant as part
        for option in ("reuse_empty_uv", "relocate_empty_uv", "upscale_textures_for_uv_reuse"):
            for invalid in ("false", 0, 1, None, [], {}):
                with self.subTest(option=option, invalid=invalid), patch.object(part, "_require_unitypy") as load:
                    with self.assertRaisesRegex(ValueError, "true or false"):
                        part.transplant_part("donor.unity", "target.unity", "output.unity", **{option: invalid})
                    load.assert_not_called()

    def test_asset_tool_and_legacy_gui_strategies_are_localized(self):
        import costume_part_transplant as part
        for language, title, labels, padding in (
            ('ko', '텍스처·UV 배치 방식', ['원래 UV 위치 재사용', '빈 UV 영역으로 이동', '새 아틀라스로 합치기'], '패딩'),
            ('ja', 'テクスチャ・UVの配置方法', ['元のUV位置を再利用', '空きUV領域へ移動', '新しいテクスチャアトラスを作成'], 'パディング')):
            with self.subTest(language=language):
                tool = next(tool for tool in registry.public_tools(language) if tool['id'] == 'costume_part_transplant')
                field = next(field for field in tool['fields'] if field['name'] == 'uv_placement')
                self.assertEqual(field['label'], title)
                self.assertEqual([option['label'] for option in field['options']], labels)
                for option in field['options']:
                    self.assertIn(padding, option['help'])
                self.assertEqual(part._TRANSLATIONS[language]['Texture and UV placement'], title)
                for original, translated in zip(('Reuse original UV positions', 'Move into empty UV areas',
                                                 'Build a new texture atlas'), labels):
                    self.assertEqual(part._TRANSLATIONS[language][original], translated)


if __name__ == '__main__':
    unittest.main()
