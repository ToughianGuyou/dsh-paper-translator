import sys
from pathlib import Path
from collections import Counter
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.math_runs import protect_math_lines, display_equation_regions, is_math_span


def span(text, font, x, y=100, size=10, width=None):
    width = width if width is not None else len(text)*4
    return {'text': text, 'font': font, 'size': size, 'flags': 0,
            'bbox': [x, y-8, x+width, y+2], 'origin': [x, y]}


def block(*lines):
    return {'_raw': {'lines': [{'spans': ss, 'dir': (1, 0)} for ss in lines]}}


class MathRunsTests(unittest.TestCase):
    def test_tex_vectors_digits_and_delimiters_are_one_run(self):
        b=block([span('Given ', 'Times-Roman', 10), span('p','CMMI10',34),
                 span('(', 'CMR10',38), span('x','CMBX10',42),
                 span('0','CMR7',46,y=102,size=7), span(')', 'CMR10',50),
                 span(' is defined.', 'Times-Roman',54)])
        text, tokens, uncertain=protect_math_lines(b,1,Counter())
        self.assertEqual(text,'Given {{MATH_00001}} is defined.')
        self.assertFalse(uncertain)
        self.assertEqual(len(tokens),1)
        self.assertEqual(tokens['{{MATH_00001}}']['bbox'],[34.,92.,54.,104.])
        self.assertEqual(tokens['{{MATH_00001}}']['baseline'],100)

    def test_prose_math_in_unknown_font_stays_uncertain(self):
        text,tokens,uncertain=protect_math_lines(block([span('x = y','Times-Roman',10)]),1,Counter())
        self.assertFalse(tokens)
        self.assertTrue(uncertain)
        self.assertEqual(text,'x = y')

    def test_small_roman_subscript_label_is_math(self):
        self.assertTrue(is_math_span(span('simple','CMR7',10,size=7),10))
        self.assertFalse(is_math_span(span('ordinary prose','CMR10',10),10))

    def test_adjacent_native_lines_form_one_visual_formula(self):
        b=block([span('p','CMMI10',10),span('(', 'CMR10',14)],
                [span('x','CMBX10',18),span(')', 'CMR10',22)])
        text,tokens,uncertain=protect_math_lines(b,1,Counter())
        self.assertEqual(text,'{{MATH_00001}}')
        self.assertEqual(len(tokens),1)
        self.assertFalse(uncertain)

    def test_footnote_literal_precedes_math_font_rule(self):
        marker=span('1','CMR7',30,size=7)
        b=block([span('text', 'Times-Roman',10),marker]);b['_footnoteTokens']={id(marker):'{{FN_00001}}'}
        text,tokens,uncertain=protect_math_lines(b,1,Counter())
        self.assertIn('{{FN_00001}}',text)
        self.assertEqual(tokens['{{FN_00001}}'],{'kind':'literal','text':'1'})

    def test_display_math_excludes_inline_prose(self):
        inline=block([span('Given ', 'Times-Roman',10),span('x','CMMI10',34)])
        display=block([span('p','CMMI10',100,y=140),span('=', 'CMR10',104,y=140),span('q','CMMI10',108,y=140,width=10)])
        regions=display_equation_regions([inline,display],10,600)
        self.assertEqual(len(regions),1)
        self.assertEqual(list(regions[0]),[100.,132.,118.,142.])

    def test_display_includes_operator_limits_fraction_and_number(self):
        numerator=block([span('p', 'CMMI10',100,y=140,width=20)])
        denominator=block([span('q', 'CMMI10',102,y=151,width=20)])
        upper=block([span('T','CMMI7',130,y=134,size=7,width=5)])
        operator=block([span('Y','CMEX10',128,y=143,width=12)])
        lower=block([span('t=1','CMR7',128,y=154,size=7,width=12)])
        label=block([span('(1)','Times-Roman',480,y=140,width=15)])
        regions=display_equation_regions([numerator,denominator,upper,operator,lower,label],10,600)
        self.assertEqual(len(regions),1)
        self.assertEqual(list(regions[0]),[100.,126.,495.,156.])

    def test_successive_body_lines_are_not_merged(self):
        b=block([span('first ', 'Times-Roman',10,y=100),span('x','CMMI10',34,y=100)],
                [span('second ', 'Times-Roman',10,y=112),span('y','CMMI10',38,y=112)])
        text,tokens,uncertain=protect_math_lines(b,1,Counter())
        self.assertEqual(text,'first {{MATH_00001}} second {{MATH_00002}}')
        self.assertEqual(len(tokens),2)
        self.assertFalse(uncertain)

    def test_display_connective_not_arbitrary_explanation(self):
        definition=block([span('where ', 'Times-Roman',90,y=140),
                          span('p', 'CMMI10',114,y=140,width=20)])
        prose=block([span('where this method applies ', 'Times-Roman',90,y=180),
                     span('q','CMMI10',194,y=180,width=20)])
        regions=display_equation_regions([definition,prose],10,600)
        self.assertEqual(len(regions),1)
        self.assertEqual(list(regions[0]),[90.,132.,134.,142.])


if __name__=='__main__':unittest.main()
