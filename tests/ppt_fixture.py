"""Minimal two-slide OOXML fixture; slide two is hidden to check page ordering."""
import io,zipfile

def pptx_bytes():
    out=io.BytesIO()
    rel='http://schemas.openxmlformats.org/package/2006/relationships'
    office='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    parts={
      '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'+''.join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in (1,2))+'</Types>',
      '_rels/.rels':f'<Relationships xmlns="{rel}"><Relationship Id="rId1" Type="{office}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
      'ppt/presentation.xml':f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="{office}"><p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>',
      'ppt/_rels/presentation.xml.rels':f'<Relationships xmlns="{rel}">'+''.join(f'<Relationship Id="rId{i}" Type="{office}/slide" Target="slides/slide{i}.xml"/>' for i in (1,2))+'</Relationships>'}
    for i in (1,2):
      hidden=' show="0"' if i==2 else ''
      parts[f'ppt/slides/slide{i}.xml']=f'''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"{hidden}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Topic"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="500000" y="500000"/><a:ext cx="8000000" cy="2500000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2800"/><a:t>Slide {i}: Independent events satisfy P(A and B) = P(A) * P(B). Probability lesson.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
      for name,xml in parts.items(): z.writestr(name,xml)
    return out.getvalue()
