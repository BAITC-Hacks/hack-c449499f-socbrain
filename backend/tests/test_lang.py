import unittest

from app.pipeline.lang import KK, MIXED, RU, UNKNOWN, detect, meeting_language


class DetectTest(unittest.TestCase):
    def test_russian(self):
        self.assertEqual(detect("Коллеги, начинаем. На повестке один вопрос, прошу коротко и по существу"), RU)

    def test_kazakh(self):
        self.assertEqual(detect("Біз бүгін жиналысты бастаймыз, сіздің баяндамаңыз қалай"), KK)

    def test_mixed(self):
        self.assertEqual(detect("біз жұмысталыға договор не можем подписать и заявка жіберіген керек"), MIXED)

    def test_single_kazakh_word_is_not_a_switch(self):
        self.assertEqual(detect("Хорошо, спасибо, на этом всё, коллеги, рахмет, мы закончили"), RU)

    def test_too_short(self):
        self.assertEqual(detect("Хорошо."), UNKNOWN)

    def test_meeting_language_by_talk_time(self):
        utterances = [{"start": 0, "end": 100, "lang": RU}, {"start": 100, "end": 130, "lang": KK}]
        self.assertEqual(meeting_language(utterances), MIXED)
        self.assertEqual(meeting_language([{"start": 0, "end": 100, "lang": RU}]), RU)


if __name__ == "__main__":
    unittest.main()
