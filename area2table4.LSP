;;---------------------=={ Area Label }==---------------------;;
;;  Author: Lee Mac, Copyright © 2011 - www.lee-mac.com       ;;
;;  Modified: Best UX / Pick Point default / MTEXT / No Fields;;

(defun c:AT nil (AT:AreaTable))
(defun c:AR nil (AT:RefreshRow))
(defun c:RT nil (AT:RebuildTotal))
(defun c:AF nil (AT:AreasToFile))

(vl-load-com)

;;------------------------------------------------------------;;
;; Settings
;;------------------------------------------------------------;;

(setq AT:Title        "Area Table"
      AT:Col1         "Survey No"
      AT:Col2         "Number"
      AT:Col3         "Area (Cents)"
      AT:NumberPrefix ""
      AT:NumberSuffix ""
      AT:ConvFactor   0.024710538
      AT:ColWidth     2.0
      AT:TextHeight   0.25
      AT:RowHeight    0.45
)

;;------------------------------------------------------------;;
;; Common Helpers
;;------------------------------------------------------------;;

(defun AT:_StartUndo (doc)
  (AT:_EndUndo doc)
  (vla-StartUndoMark doc)
)

(defun AT:_EndUndo (doc)
  (if (= 8 (logand 8 (getvar 'UNDOCTL)))
    (vla-EndUndoMark doc)
  )
)

(defun AT:_Open (target / Shell result)
  (if (setq Shell (vla-getInterfaceObject (vlax-get-acad-object) "Shell.Application"))
    (progn
      (setq result
        (and
          (or (eq 'INT (type target)) (setq target (findfile target)))
          (not
            (vl-catch-all-error-p
              (vl-catch-all-apply 'vlax-invoke (list Shell 'Open target))
            )
          )
        )
      )
      (vlax-release-object Shell)
    )
  )
  result
)

(defun AT:_Select (msg pred func init / e)
  (setq pred (eval pred))
  (while
    (progn
      (setvar 'ERRNO 0)
      (apply 'initget init)
      (setq e (func msg))
      (cond
        ((= 7 (getvar 'ERRNO))
         (princ "\nMissed, try again."))
        ((eq 'STR (type e))
         nil)
        ((vl-consp e)
         (if (and pred (not (pred (setq e (car e)))))
           (princ "\nInvalid object selected.")
         )
        )
      )
    )
  )
  e
)

(defun AT:_GetDoc nil
  (vla-get-ActiveDocument (vlax-get-acad-object))
)

(defun AT:_GetSpace (doc)
  (vlax-get-property doc (if (= 1 (getvar 'CVPORT)) 'Paperspace 'Modelspace))
)

(defun AT:_Centroid (space objs / reg cen)
  (setq reg (car (vlax-invoke space 'addregion objs))
        cen (vlax-get reg 'centroid))
  (vla-delete reg)
  (trans cen 1 0)
)

(defun AT:_AddMTextLabel (space point string height rotation / obj)
  (setq obj (vla-addmtext space (vlax-3D-point point) 0.0 string))
  (vla-put-attachmentpoint obj acAttachmentPointMiddleCenter)
  (vla-put-height obj height)
  (vla-put-rotation obj rotation)
  obj
)

(defun AT:_CreateTableStyle (doc / dictTblStyles tblStyle styleExists)
  (vl-catch-all-apply
    '(lambda (/ dictTblStyles tblStyle styleExists)
       (setq dictTblStyles (vla-get-dictionaries doc))
       (setq dictTblStyles (vla-item dictTblStyles "ACAD_TABLESTYLE"))
       (setq styleExists
         (not
           (vl-catch-all-error-p
             (vl-catch-all-apply 'vla-item (list dictTblStyles "Archii Table"))
           )
         )
       )
       (if (not styleExists)
         (progn
           (setq tblStyle (vla-addobject dictTblStyles "Archii Table" "AcDbTableStyle"))
           (vla-settextheight tblStyle acTitleRow  0.35)
           (vla-settextheight tblStyle acHeaderRow 0.30)
           (vla-settextheight tblStyle acDataRow   0.25)
           (vla-setalignment tblStyle acTitleRow  acMiddleCenter)
           (vla-setalignment tblStyle acHeaderRow acMiddleCenter)
           (vla-setalignment tblStyle acDataRow   acMiddleCenter)
           (princ "\nTable Style 'Archii Table' created successfully.")
         )
         (princ "\nTable Style 'Archii Table' already exists.")
       )
     )
  )
)

(defun AT:_MakeBoundaryAtPoint (pt / el)
  (setq el (entlast))
  (vl-cmdf "_.-boundary" "_A" "_I" "_N" "" "_O" "_P" "" "_non" pt "")
  (if (not (equal el (setq el (entlast))))
    el
    nil
  )
)

(defun AT:_AreaCentsFromPoint (pt / el val)
  (if (setq el (AT:_MakeBoundaryAtPoint pt))
    (progn
      (setq val (rtos (* AT:ConvFactor (vlax-curve-getarea el)) 2 3))
      (entdel el)
      val
    )
    nil
  )
)

(defun AT:_AreaCentsFromObject (en / obj)
  (setq obj (vlax-ename->vla-object en))
  (if (and
        (vlax-property-available-p obj 'Area)
        (not (eq "HATCH" (cdr (assoc 0 (entget en)))))
        (or (eq "REGION" (cdr (assoc 0 (entget en))))
            (vlax-curve-isclosed en))
      )
    (rtos (* AT:ConvFactor (vla-get-area obj)) 2 3)
    nil
  )
)

(defun AT:_CentroidFromPoint (space pt / el cen)
  (if (setq el (AT:_MakeBoundaryAtPoint pt))
    (progn
      (setq cen (AT:_Centroid space (list (vlax-ename->vla-object el))))
      (entdel el)
      cen
    )
    nil
  )
)

(defun AT:_CentroidFromObject (space en / objname)
  (setq objname (vlax-ename->vla-object en))
  (AT:_Centroid space (list objname))
)

(defun AT:_SetTotalFormula (tb / rows r)
  (setq rows (vla-get-rows tb)
        r    (1- rows))
  (cond
    ((<= rows 3)
     (vla-settext tb r 2 "0.000")
     (vl-catch-all-apply 'vla-SetCellFormat (list tb r 2 "%lu2%pr3"))
    )
    (t
     (vla-settext tb r 2
       (strcat "=Sum(C3:C" (itoa r) ")"))
     (vl-catch-all-apply 'vla-SetCellFormat (list tb r 2 "%lu2%pr3"))
    )
  )
)

(defun AT:_PrepareTotalRow (tb)
  (vla-settext tb (1- (vla-get-rows tb)) 0 "")
  (vla-settext tb (1- (vla-get-rows tb)) 1 "TOTAL")
  (AT:_SetTotalFormula tb)
)

(defun AT:_NewTable (space pt / tb)
  (setq tb
    (vla-addtable space
      (vlax-3D-point (trans pt 1 0)) 3 3 AT:RowHeight AT:ColWidth
    )
  )
  (vla-put-direction tb (vlax-3D-point (getvar 'UCSXDIR)))
  (vl-catch-all-apply 'vla-put-stylename (list tb "Archii Table"))
  (vla-setrowheight tb 0 1.2)
  (vla-setrowheight tb 1 0.9)
  (vla-setrowheight tb 2 AT:RowHeight)
  (vla-setcolumnwidth tb 0 AT:ColWidth)
  (vla-setcolumnwidth tb 1 AT:ColWidth)
  (vla-setcolumnwidth tb 2 AT:ColWidth)
  (vla-settext tb 0 0 AT:Title)
  (vla-settext tb 1 0 AT:Col1)
  (vla-settext tb 1 1 AT:Col2)
  (vla-settext tb 1 2 AT:Col3)
  (vla-settext tb 2 0 "")
  (vla-settext tb 2 1 "TOTAL")
  (vla-settext tb 2 2 "0.000")
  tb
)

(defun AT:_AddDataRow (tb num areatxt / totalrow newrow)
  (setq totalrow (1- (vla-get-rows tb)))
  (vla-insertrows tb totalrow AT:RowHeight 1)
  (setq newrow totalrow)
  (vla-settext tb newrow 0 "")
  (vla-settext tb newrow 1 (strcat AT:NumberPrefix (itoa num) AT:NumberSuffix))
  (vla-settext tb newrow 2 areatxt)
  (AT:_PrepareTotalRow tb)
  newrow
)

(defun AT:_DataRowValidP (tb row)
  (and (>= row 2)
       (< row (1- (vla-get-rows tb))))
)

(defun AT:_GetStartingNumber nil
  (cond
    ((getint
       (strcat "\nSpecify Starting Number <"
               (itoa (setq *al:num (cond (*al:num) (1))))
               ">: "
       )
     )
    )
    (*al:num)
  )
)

(defun AT:_GetTable nil
  (if (setq tb
        (AT:_Select "\nSelect Table: "
          '(lambda (x) (eq "ACAD_TABLE" (cdr (assoc 0 (entget x)))))
          entsel nil
        )
      )
    (vlax-ename->vla-object tb)
  )
)

(defun AT:_GetTableForTotal nil
  (if (setq tb
        (AT:_Select "\nSelect Table to rebuild total: "
          '(lambda (x) (eq "ACAD_TABLE" (cdr (assoc 0 (entget x)))))
          entsel nil
        )
      )
    (vlax-ename->vla-object tb)
  )
)

(defun AT:_LabelPointRotation nil
  (list
    (trans '(0. 0. 1.) 1 0 t)
    (angle '(0. 0. 0.) (trans (getvar 'UCSXDIR) 0 (trans '(0. 0. 1.) 1 0 t)))
  )
)

(defun AT:_ParseRowInput (s / u n)
  (setq u (strcase (vl-string-trim " " s)))
  (cond
    ((wcmatch u "C#*")
     (setq n (atoi (substr u 2)))
     (if (> n 0) (1- n))
    )
    ((wcmatch u "#*")
     (+ 1 (atoi u))
    )
    (t nil)
  )
)

(defun AT:_SelectClosedObject nil
  (AT:_Select
    "\nSelect enclosed Object: "
    '(lambda (x)
       (and
         (vlax-property-available-p (vlax-ename->vla-object x) 'Area)
         (not (eq "HATCH" (cdr (assoc 0 (entget x)))))
         (or (eq "REGION" (cdr (assoc 0 (entget x))))
             (vlax-curve-isclosed x))
       )
     )
    entsel nil
  )
)

;;------------------------------------------------------------;;
;; AT - Areas to Table
;;------------------------------------------------------------;;

(defun AT:AreaTable (/ *error* doc space cm meta p1 tb tx row areatxt cen obj undoitem)
  (defun *error* (msg)
    (if cm (setvar 'CMDECHO cm))
    (if doc (AT:_EndUndo doc))
    (if (null (wcmatch (strcase msg) "*BREAK,*CANCEL*,*EXIT*"))
      (princ (strcat "\n--> Error: " msg))
    )
    (princ)
  )

  (setq doc (AT:_GetDoc)
        space (AT:_GetSpace doc)
        meta (AT:_LabelPointRotation)
  )

  (AT:_CreateTableStyle doc)
  (AT:_StartUndo doc)
  (setq cm (getvar 'CMDECHO))
  (setvar 'CMDECHO 0)

  (cond
    ((not (vlax-method-applicable-p space 'addtable))
     (princ "\nTable Objects not available in this version.")
    )
    ((= 4 (logand 4 (cdr (assoc 70 (tblsearch "LAYER" (getvar 'CLAYER))))))
     (princ "\nCurrent layer locked.")
    )
    ((not (setq *al:num (AT:_GetStartingNumber))))
    (t
     (setq tb
       (cond
         ((progn
            (initget "Add")
            (vl-consp (setq p1 (getpoint "\nPick Point for Table <Add to Existing>: ")))
          )
          (AT:_NewTable space p1)
         )
         ((progn
            (setq tb (AT:_GetTable))
            (and tb (< 2 (vla-get-columns tb)))
          )
          tb
         )
       )
     )

     (if tb
       (progn
         (if (> (vla-get-rows tb) 3)
           (setq *al:num (- (vla-get-rows tb) 2))
         )

         (setq tx '())
         (while
           (progn
             (initget "Object Undo")
             (setq p1 (getpoint "\nPick enclosed Area [Object/Undo] <Finish>: "))
             (cond
               ((null p1) nil)

               ((eq p1 "Undo")
                (if tx
                  (progn
                    (setq undoitem (car tx))
                    (vla-deleterows tb (car undoitem) 1)
                    (if (and (cadr undoitem) (not (vlax-erased-p (cadr undoitem))))
                      (vla-delete (cadr undoitem))
                    )
                    (setq tx (cdr tx))
                    (setq *al:num (1- *al:num))
                    (AT:_PrepareTotalRow tb)
                  )
                  (princ "\n--> Nothing to Undo.")
                )
                t
               )

               ((eq p1 "Object")
                (if (setq obj (AT:_SelectClosedObject))
                  (if (and
                        (setq areatxt (AT:_AreaCentsFromObject obj))
                        (setq cen (AT:_CentroidFromObject space obj))
                      )
                    (progn
                      (setq row (AT:_AddDataRow tb *al:num areatxt))
                      (setq tx
                        (cons
                          (list row
                                (AT:_AddMTextLabel space cen
                                  (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix)
                                  AT:TextHeight
                                  (cadr meta)
                                )
                          )
                          tx
                        )
                      )
                      (setq *al:num (1+ *al:num))
                    )
                    (princ "\n--> Invalid enclosed object selected.")
                  )
                  (princ "\n--> Invalid enclosed object selected.")
                )
                t
               )

               ((vl-consp p1)
                (if (and
                      (setq areatxt (AT:_AreaCentsFromPoint p1))
                      (setq cen (AT:_CentroidFromPoint space p1))
                    )
                  (progn
                    (setq row (AT:_AddDataRow tb *al:num areatxt))
                    (setq tx
                      (cons
                        (list row
                              (AT:_AddMTextLabel space cen
                                (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix)
                                AT:TextHeight
                                (cadr meta)
                              )
                        )
                        tx
                      )
                    )
                    (setq *al:num (1+ *al:num))
                  )
                  (princ "\n--> Boundary not closed or point not inside enclosed region.")
                )
                t
               )
             )
           )
         )
       )
     )
    )
  )

  (setvar 'CMDECHO cm)
  (AT:_EndUndo doc)
  (princ)
)

;;------------------------------------------------------------;;
;; AR - Refresh One Row
;;------------------------------------------------------------;;

(defun AT:RefreshRow (/ *error* doc cm tb sin row p1 obj areatxt)
  (defun *error* (msg)
    (if cm (setvar 'CMDECHO cm))
    (if doc (AT:_EndUndo doc))
    (if (null (wcmatch (strcase msg) "*BREAK,*CANCEL*,*EXIT*"))
      (princ (strcat "\n--> Error: " msg))
    )
    (princ)
  )

  (setq doc (AT:_GetDoc))
  (AT:_StartUndo doc)
  (setq cm (getvar 'CMDECHO))
  (setvar 'CMDECHO 0)

  (if (setq tb (AT:_GetTable))
    (progn
      (setq sin (getstring t "\nEnter data row number to refresh [e.g. 1 or C3]: "))
      (setq row (AT:_ParseRowInput sin))
      (cond
        ((null row)
         (princ "\n--> Invalid row input. Enter serial number like 1 or cell reference like C3.")
        )
        ((not (AT:_DataRowValidP tb row))
         (princ "\n--> Invalid data row. Do not select title, header, or total row.")
        )
        (t
         (initget "Object")
         (setq p1 (getpoint "\nPick enclosed Area [Object]: "))
         (cond
           ((eq p1 "Object")
            (if (setq obj (AT:_SelectClosedObject))
              (setq areatxt (AT:_AreaCentsFromObject obj))
              (princ "\n--> Invalid enclosed object selected.")
            )
           )
           ((vl-consp p1)
            (setq areatxt (AT:_AreaCentsFromPoint p1))
           )
         )

         (if areatxt
           (progn
             (vla-settext tb row 2 areatxt)
             (AT:_PrepareTotalRow tb)
             (princ "\nRow refreshed successfully.")
           )
           (princ "\n--> Boundary not closed or point not inside enclosed region.")
         )
        )
      )
    )
  )

  (setvar 'CMDECHO cm)
  (AT:_EndUndo doc)
  (princ)
)

;;------------------------------------------------------------;;
;; RT - Rebuild Total
;;------------------------------------------------------------;;

(defun AT:RebuildTotal (/ *error* doc cm tb)
  (defun *error* (msg)
    (if cm (setvar 'CMDECHO cm))
    (if doc (AT:_EndUndo doc))
    (if (null (wcmatch (strcase msg) "*BREAK,*CANCEL*,*EXIT*"))
      (princ (strcat "\n--> Error: " msg))
    )
    (princ)
  )

  (setq doc (AT:_GetDoc))
  (AT:_StartUndo doc)
  (setq cm (getvar 'CMDECHO))
  (setvar 'CMDECHO 0)

  (if (setq tb (AT:_GetTableForTotal))
    (progn
      (AT:_PrepareTotalRow tb)
      (princ "\nTotal rebuilt successfully.")
    )
  )

  (setvar 'CMDECHO cm)
  (AT:_EndUndo doc)
  (princ)
)

;;------------------------------------------------------------;;
;; AF - Areas to File
;;------------------------------------------------------------;;

(defun AT:AreasToFile (/ *error* doc space cm meta fl of de p1 el obj areaTxt)
  (defun *error* (msg)
    (if cm (setvar 'CMDECHO cm))
    (if el (progn (entdel el) (setq el nil)))
    (if doc (AT:_EndUndo doc))
    (if (and of (eq 'FILE (type of))) (close of))
    (if (null (wcmatch (strcase msg) "*BREAK,*CANCEL*,*EXIT*"))
      (princ (strcat "\n--> Error: " msg))
    )
    (princ)
  )

  (setq doc   (AT:_GetDoc)
        space (AT:_GetSpace doc)
        meta  (AT:_LabelPointRotation)
  )

  (AT:_StartUndo doc)
  (setq cm (getvar 'CMDECHO))
  (setvar 'CMDECHO 0)

  (if (and
        (setq *al:num
          (cond
            ((getint
               (strcat "\nSpecify Starting Number <"
                       (itoa (setq *al:num (cond (*al:num) (1))))
                       ">: "
               )
             )
            )
            (*al:num)
          )
        )
        (setq fl (getfiled "Create Output File" (cond (*file*) ("")) "txt;csv;xls" 1))
        (setq of (open fl "w"))
      )
    (progn
      (setq *file* (vl-filename-directory fl)
            de     (cdr (assoc (strcase (vl-filename-extension fl) t)
                          '((".txt" . "\t") (".csv" . ",") (".xls" . "\t"))))
      )
      (write-line AT:Title of)
      (write-line (strcat AT:Col1 de AT:Col2 de AT:Col3) of)

      (while
        (progn
          (initget "Object")
          (setq p1 (getpoint "\nPick enclosed Area [Object] <Finish>: "))
          (cond
            ((null p1) nil)

            ((eq p1 "Object")
             (if (setq obj (AT:_SelectClosedObject))
               (progn
                 (setq areaTxt (AT:_AreaCentsFromObject obj))
                 (AT:_AddMTextLabel space
                   (AT:_CentroidFromObject space obj)
                   (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix)
                   AT:TextHeight
                   (cadr meta)
                 )
                 (write-line
                   (strcat "" de
                           (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix) de
                           areaTxt)
                   of
                 )
                 (setq *al:num (1+ *al:num))
               )
               (princ "\n--> Invalid enclosed object selected.")
             )
             t
            )

            ((vl-consp p1)
             (if (setq el (AT:_MakeBoundaryAtPoint p1))
               (progn
                 (AT:_AddMTextLabel space
                   (AT:_Centroid space (list (vlax-ename->vla-object el)))
                   (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix)
                   AT:TextHeight
                   (cadr meta)
                 )
                 (write-line
                   (strcat "" de
                           (strcat AT:NumberPrefix (itoa *al:num) AT:NumberSuffix) de
                           (rtos (* AT:ConvFactor (vlax-curve-getarea el)) 2 3))
                   of
                 )
                 (setq *al:num (1+ *al:num))
                 (entdel el)
                 (setq el nil)
               )
               (princ "\n--> Boundary not closed or point not inside enclosed region.")
             )
             t
            )
          )
        )
      )

      (setq of (close of))
      (AT:_Open (findfile fl))
    )
  )

  (setvar 'CMDECHO cm)
  (AT:_EndUndo doc)
  (princ)
)

(princ)