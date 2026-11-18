import io
import unittest
import pymupdf
from PIL import Image, ImageDraw
from src.visual_regions import page_regions,iter_regions


def picture():
    with Image.new('RGB',(300,300),'white') as image:
        ImageDraw.Draw(image).rectangle((30,30,270,270),fill='blue')
        data=io.BytesIO();image.save(data,format='PNG');return data.getvalue()


class VisualRegionTests(unittest.TestCase):
    def test_image_and_vector_regions_retain_page_and_bounds(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_image(pymupdf.Rect(50,200,350,500),stream=picture())
            page.draw_rect(pymupdf.Rect(100,550,400,750))
            regions=page_regions(page)
            self.assertTrue(any(r.kind=='image' and r.bbox==(50.,200.,350.,500.) for r in regions))
            self.assertTrue(any(r.kind=='diagram' for r in regions))
            self.assertTrue(all(r.page==1 for r in regions))
            content=doc.tobytes()
        seen=[]
        for region,image in iter_regions('example.pdf',content):
            self.assertLessEqual(max(image.size),1025)
            seen.append(image)
        self.assertTrue(seen)
        for image in seen:
            with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_full_page_scan_gets_zoomed_tiles_and_no_banner_crop(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_image(page.rect,stream=picture(),keep_proportion=False)
            regions=page_regions(page)
            self.assertEqual([r.kind for r in regions],['tile','tile'])
            self.assertEqual(len(page_regions(page,max_regions=1)),1)
            self.assertTrue(all(pymupdf.Rect(r.bbox).get_area()<page.rect.get_area() for r in regions))

    def test_region_budget_and_blank_page(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            self.assertEqual(page_regions(page),[])
            for i in range(5):page.draw_rect(pymupdf.Rect(30,30+i*145,250,150+i*145))
            self.assertLessEqual(len(page_regions(page,max_regions=2)),2)

    def test_invalid_budget_is_rejected(self):
        with pymupdf.open() as document:
            page=document.new_page()
            with self.assertRaises(ValueError):page_regions(page,max_regions=0)
