"""Game-facing asset tools reuse UVs by default and relocate only by request."""
import unittest
from unittest.mock import patch

from webtools.jobs import Job
from webtools.tools import costume, registry


class ReuseEmptyUVToolTests(unittest.TestCase):
    def test_part_tool_uv_defaults_and_existing_physics_defaults_are_kept(self):
        fields = {field['name']: field for field in registry.get_tool('costume_part_transplant')['fields']}
        self.assertEqual(fields['reuse_empty_uv']['type'], 'checkbox')
        self.assertIs(fields['reuse_empty_uv']['default'], True)
        self.assertIs(fields['relocate_empty_uv']['default'], False)
        self.assertEqual(fields['relocate_empty_uv']['type'], 'checkbox')
        self.assertIn('occupied', fields['reuse_empty_uv']['help'])
        self.assertIn('No padding', fields['reuse_empty_uv']['help'])
        self.assertIs(fields['preserve_physics']['default'], True)
        self.assertIs(fields['restore_collision']['default'], True)

    def test_asset_tool_rejects_non_boolean_uv_reuse_before_loading_or_writing(self):
        for option in ('reuse_empty_uv', 'relocate_empty_uv'):
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

    def test_asset_tool_and_legacy_checkbox_are_localized(self):
        import costume_part_transplant as part
        for language, expected, relocation, phrase in (('ko', '빈 UV 영역 재사용', '다른 빈 UV 영역으로 옮기기', '패딩'),
                                           ('ja', '空きUV領域を再利用', '別の空きUV領域へ移動', 'パディング')):
            with self.subTest(language=language):
                tool = next(tool for tool in registry.public_tools(language) if tool['id'] == 'costume_part_transplant')
                field = next(field for field in tool['fields'] if field['name'] == 'reuse_empty_uv')
                self.assertEqual(field['label'], expected)
                self.assertIn(phrase, field['help'])
                relocate = next(field for field in tool['fields'] if field['name'] == 'relocate_empty_uv')
                self.assertEqual(relocate['label'], relocation)
                self.assertIn(phrase, relocate['help'])
                self.assertIn(expected.split(' (')[0],
                    part._TRANSLATIONS[language]['Reuse empty UV areas (otherwise build a texture atlas)'])


if __name__ == '__main__':
    unittest.main()
