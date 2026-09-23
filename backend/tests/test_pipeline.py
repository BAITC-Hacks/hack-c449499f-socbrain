import unittest

from app.pipeline.align import to_utterances
from app.pipeline.diarization import Turn, merge_minor_speakers
from app.pipeline.extract import canonical_name, match_speaker, rule_based_tasks
from app.stt import TranscriptWord


class MergeMinorSpeakersTest(unittest.TestCase):
    def test_short_voice_goes_to_nearest_speaker(self):
        turns = [Turn(0, 10, "A"), Turn(10.6, 10.9, "NOISE"), Turn(11, 20, "B")]
        merged = merge_minor_speakers(turns)
        self.assertEqual([t.speaker for t in merged], ["A", "B", "B"])

    def test_tie_goes_to_previous_speaker(self):
        turns = [Turn(0, 10, "A"), Turn(10.2, 10.8, "NOISE"), Turn(11, 20, "B")]
        self.assertEqual([t.speaker for t in merge_minor_speakers(turns)], ["A", "A", "B"])

    def test_all_real_speakers_untouched(self):
        turns = [Turn(0, 10, "A"), Turn(10, 20, "B")]
        self.assertEqual([t.speaker for t in merge_minor_speakers(turns)], ["A", "B"])


class AlignTest(unittest.TestCase):
    def test_words_split_by_speaker_and_language_detected(self):
        words = [TranscriptWord(0.0, 0.5, " Коллеги,"), TranscriptWord(0.5, 1.0, " начинаем,"),
                 TranscriptWord(1.0, 1.5, " это"), TranscriptWord(1.5, 2.0, " не"),
                 TranscriptWord(2.1, 2.5, " Спасибо.")]
        turns = [Turn(0, 2.0, "SPEAKER_00"), Turn(2.0, 3.0, "SPEAKER_01")]
        utterances = to_utterances(words, turns)
        self.assertEqual([u["speaker"] for u in utterances], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual(utterances[0]["text"], "Коллеги, начинаем, это не")
        self.assertEqual(utterances[0]["lang"], "ru")


class NamesTest(unittest.TestCase):
    PARTICIPANTS = ["Тимур Болатович — директор департамента инвестиций", "Нурлан Сагатович — охрана труда"]

    def test_asr_typo_fixed_by_participant_card(self):
        self.assertEqual(canonical_name("Тимур Булотович", self.PARTICIPANTS), "Тимур Болатович")
        self.assertEqual(canonical_name("Нурлан Согатович", self.PARTICIPANTS), "Нурлан Сагатович")

    def test_department_is_not_forced_to_a_person(self):
        self.assertEqual(canonical_name("юридический департамент", self.PARTICIPANTS), "юридический департамент")

    def test_match_speaker(self):
        speakers = [{"label": "SPEAKER_00", "name": "Асхат Ерланович"}, {"label": "SPEAKER_03", "name": "Тимур Болатович"}]
        self.assertEqual(match_speaker("Тимур Балатович", speakers), "SPEAKER_03")
        self.assertIsNone(match_speaker("Ерлан", speakers))


class RuleBasedTasksTest(unittest.TestCase):
    def test_explicit_form_from_asr(self):
        text = ("Фиксируем поручение. Первое – разработать единую стратегию закупа сырья для химических активов "
                "группы, ответственный Гульмира Сериковна, срок до 15 октября.")
        tasks = rule_based_tasks([{"speaker": "SPEAKER_00", "text": text}])
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["description"].startswith("разработать единую стратегию"))
        self.assertEqual(tasks[0]["assignee"], "Гульмира Сериковна")
        self.assertEqual(tasks[0]["deadline_text"], "до 15 октября")


if __name__ == "__main__":
    unittest.main()
