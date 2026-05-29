;;; ============================================================
;;; DWG SMART BOX - FULL CORRECTED VERSION
;;; Command   : DN
;;; Command   : DNUPDATE
;;; Command   : DNEDIT (commented out - reserved)
;;;
;;; Layer     : A_Dwgblock
;;; Entity colour : ByBlock (0)
;;; Month     : 05 format
;;; Text height : 0.23 (meter) / 9.0 (feet-inches)
;;; Pick point : CENTER of box
;;; Padding    : w1pad / w2pad / w3pad / offy (fixed setq)
;;; Border lineweight : 0.35mm (35)
;;; Unit detection : INSUNITS + LUNITS (both checked)
;;; ============================================================

(vl-load-com)

(setq *dwg-blockname* "DWGNO_BOX")

;;; ================================================================
;;; UNIT DETECTION
;;; INSUNITS : 1=Inches  2=Feet
;;; LUNITS   : 3=Engineering  4=Architectural
;;; ================================================================

(defun _is-feet-inches nil
  (or
    (member (getvar "INSUNITS") '(1 2))
    (member (getvar "LUNITS")   '(3 4))
  )
)

(defun _default-text-height nil
  (if (_is-feet-inches)
    9.0
    0.23
  )
)

;;; ================================================================
;;; HELPERS
;;; ================================================================

(defun _doc nil
  (vla-get-ActiveDocument (vlax-get-acad-object))
)

(defun _space (doc)
  (if (= 1 (getvar "CVPORT"))
    (vla-get-PaperSpace doc)
    (vla-get-ModelSpace doc)
  )
)

(defun _dwg-no (/ fname base pos prefix)
  (setq fname  (getvar "DWGNAME"))
  (setq prefix (if (_is-feet-inches) "M" ""))
  (if (and fname (/= fname ""))
    (progn
      (setq base (vl-filename-base fname))
      (setq pos  (vl-string-search "." base))
      (strcat
        prefix
        (if pos
          (substr base 1 pos)
          base
        )
      )
    )
    (strcat prefix "UNNAMED")
  )
)

(defun _month-year (/ dt y m)
  (setq dt (fix (getvar "CDATE")))
  (setq y  (itoa (/ dt 10000)))
  (setq m  (itoa (rem (/ dt 100) 100)))
  (if (= (strlen m) 1)
    (setq m (strcat "0" m))
  )
  (list m y)
)

;;; ================================================================
;;; LAYER
;;; ================================================================

(defun _make-layer (lname lweight / doc layers layer)
  (setq doc    (_doc))
  (setq layers (vla-get-Layers doc))
  (if
    (vl-catch-all-error-p
      (setq layer
        (vl-catch-all-apply
          'vla-Item (list layers lname)
        )
      )
    )
    (progn
      (setq layer (vla-Add layers lname))
      (princ (strcat "\nLayer created  : " lname))
    )
    (princ (strcat "\nLayer exists   : " lname))
  )
  (vla-put-Lineweight layer lweight)
  (vl-catch-all-apply
    '(lambda ()
       (vla-put-LayerOn layer :vlax-true)
       (vla-put-Freeze  layer :vlax-false)
       (vla-put-Lock    layer :vlax-false)
     )
  )
  layer
)

(defun _set-common-props (obj lname /)
  (vla-put-Layer obj lname)
  (vla-put-Color obj 0)
)

;;; ================================================================
;;; SAFEARRAY FOR LWPOLYLINE
;;; ================================================================

(defun _pts->sa (pts / arr i)
  (setq arr
    (vlax-make-safearray
      vlax-vbdouble
      (cons 0 (1- (* 2 (length pts))))
    )
  )
  (setq i 0)
  (foreach p pts
    (vlax-safearray-put-element arr i      (float (car  p)))
    (vlax-safearray-put-element arr (1+ i) (float (cadr p)))
    (setq i (+ i 2))
  )
  arr
)

;;; ================================================================
;;; VLA ADD ENTITIES TO BLOCK
;;; ================================================================

(defun _add-pline (blk pts closed lname / obj)
  (setq obj
    (vla-AddLightWeightPolyline blk (_pts->sa pts))
  )
  (if closed
    (vla-put-Closed obj :vlax-true)
  )
  (vla-put-Lineweight obj 35)
  (_set-common-props obj lname)
  obj
)

(defun _add-line (blk p1 p2 lname / obj)
  (setq obj
    (vla-AddLine blk
      (vlax-3d-point p1)
      (vlax-3d-point p2)
    )
  )
  (_set-common-props obj lname)
  obj
)

(defun _add-mtext (blk pt txt ht lname / obj)
  (setq obj
    (vla-AddMText blk (vlax-3d-point pt) 0.0 txt)
  )
  (vla-put-Height          obj ht)
  (vla-put-AttachmentPoint obj acAttachmentPointMiddleCenter)
  (vla-put-InsertionPoint  obj (vlax-3d-point pt))
  (_set-common-props obj lname)
  (vla-Update obj)
  obj
)

(defun _add-attdef (blk pt ht tag defval lname / obj)
  (setq obj
    (vla-AddAttribute
      blk
      (float ht)
      0
      tag
      (vlax-3d-point pt)
      tag
      defval
    )
  )
  (vla-put-Alignment          obj 10)
  (vla-put-TextAlignmentPoint obj (vlax-3d-point pt))
  (_set-common-props obj lname)
  (vla-Update obj)
  obj
)

;;; ================================================================
;;; BLOCK EXISTS / DELETE
;;; ================================================================

(defun _block-exists (bname / doc blks)
  (setq doc  (_doc))
  (setq blks (vla-get-Blocks doc))
  (not
    (vl-catch-all-error-p
      (vl-catch-all-apply
        'vla-Item (list blks bname)
      )
    )
  )
)

(defun _delete-block (bname / doc blks)
  (setq doc  (_doc))
  (setq blks (vla-get-Blocks doc))
  (vl-catch-all-apply
    '(lambda ()
       (vla-Delete (vla-Item blks bname))
       (princ (strcat "\nOld block deleted  : " bname))
     )
  )
)

;;; ================================================================
;;; UPDATE ALL INSERTS
;;; ================================================================

(defun _update-all-blocks (/ no ss i en bname obj atts count)
  (setq no    (_dwg-no))
  (setq count 0)
  (setq ss
    (ssget "_X" (list (cons 0 "INSERT")))
  )
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq en    (ssname ss i))
        (setq bname (cdr (assoc 2 (entget en))))
        (if (= bname *dwg-blockname*)
          (progn
            (setq obj (vlax-ename->vla-object en))
            (setq atts
              (vl-catch-all-apply
                'vlax-invoke (list obj 'GetAttributes)
              )
            )
            (if (not (vl-catch-all-error-p atts))
              (foreach att atts
                (if (= (strcase (vla-get-TagString att)) "DWGNO")
                  (progn
                    (vla-put-TextString att no)
                    (vla-Update att)
                    (setq count (1+ count))
                  )
                )
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ
        (strcat
          "\n" (itoa count)
          " Drawing Number block(s) updated to: " no
        )
      )
    )
    (princ "\nNo INSERT entities found in drawing.")
  )
  (vl-catch-all-apply
    '(lambda () (command "_.REGEN"))
  )
)

;;; ================================================================
;;; REACTOR
;;; ================================================================

(defun _on-save (r p)
  (vl-catch-all-apply '_update-all-blocks)
)

(defun _on-open (r p)
  (vl-catch-all-apply '_update-all-blocks)
)

(defun _make-reactor nil
  (vl-catch-all-apply
    '(lambda ()
       (vlr-dwg-reactor nil
         '((:vlr-beginSave  . _on-save)
           (:vlr-beginClose . _on-save)
         )
       )
     )
  )
  (vl-catch-all-apply
    '(lambda ()
       (vlr-editor-reactor nil
         '((:vlr-beginDwgOpen . _on-open))
       )
     )
  )
)

;;; ================================================================
;;; ERROR HANDLER
;;; ================================================================

(defun *error* (msg)
  (if (not
        (member msg
          '("Function cancelled"
            "quit / exit abort"
            ""
           )
        )
      )
    (princ (strcat "\nDWG Error: " msg))
  )
  (vl-catch-all-apply
    '(lambda ()
       (vla-EndUndoMark (_doc))
     )
  )
  (princ)
)

;;; ================================================================
;;; BUILD BLOCK DEFINITION
;;;
;;; w1pad / w2pad / w3pad
;;;   = fixed padding values set by setq in c:dn
;;;   = total horizontal space added to each column
;;;   = left gap + right gap inside cell border
;;;   = completely independent of text height
;;;
;;; COLUMN WIDTH:
;;;   w1 = max( (strlen x ht x 0.83) + w1pad , ht x 3.0 )
;;;   w2 = max( (strlen x ht x 0.83) + w2pad , ht x 2.8 )
;;;   w3 = max( (strlen x ht x 0.83) + w3pad , ht x 3.0 )
;;;
;;; ROW HEIGHT:
;;;   h2 = (ht x 2.0) + offy   lower row
;;;   h1 = (ht x 2.2) + offy   upper title row
;;;   offy = fixed vertical padding set by setq in c:dn
;;; ================================================================

(defun _build-block
       (bname ht w1pad w2pad w3pad offy noStr moStr yrStr lname
        / doc blks blkDef
          h1 h2 w1 w2 w3
          ox oy totalW totalH
          ydiv xdiv1 xdiv2
          cTitle cNo cMo cYr)

  (setq doc  (_doc))
  (setq blks (vla-get-Blocks doc))

  (if (_block-exists bname)
    (_delete-block bname)
  )

  ;;----------------------------------------------------------
  ;; ROW HEIGHTS
  ;; offy = fixed vertical padding (set in c:dn)
  ;;----------------------------------------------------------
  (setq h2 (+ (* ht 2.0) offy))
  (setq h1 (+ (* ht 2.2) offy))

  ;;----------------------------------------------------------
  ;; COLUMN WIDTHS
  ;; multiplier 0.83 => w3 = 4 x 9.0 x 0.83 = 29.88" ~ 2'6"
  ;; w1pad / w2pad / w3pad = fixed gap values from c:dn
  ;;----------------------------------------------------------
  (setq w1
    (max
      (+ (* (strlen noStr) ht 0.83) w1pad)
      (* ht 3.0)
    )
  )
  (setq w2
    (max
      (+ (* (strlen moStr) ht 0.83) w2pad)
      (* ht 2.8)
    )
  )
  (setq w3
    (max
      (+ (* (strlen yrStr) ht 0.83) w3pad)
      (* ht 3.0)
    )
  )

  (setq totalW (+ w1 w2 w3))
  (setq totalH (+ h1 h2))
  (setq ox 0.0)
  (setq oy 0.0)

  (setq ydiv  (+ oy h2))
  (setq xdiv1 (+ ox w1))
  (setq xdiv2 (+ ox w1 w2))

  ;;----------------------------------------------------------
  ;; TEXT CENTRE POINTS FOR EACH CELL
  ;;----------------------------------------------------------
  (setq cTitle
    (list
      (+ ox (/ totalW 2.0))
      (+ oy h2 (/ h1 2.0))
      0.0
    )
  )
  (setq cNo
    (list
      (+ ox (/ w1 2.0))
      (+ oy (/ h2 2.0))
      0.0
    )
  )
  (setq cMo
    (list
      (+ ox w1 (/ w2 2.0))
      (+ oy (/ h2 2.0))
      0.0
    )
  )
  (setq cYr
    (list
      (+ ox w1 w2 (/ w3 2.0))
      (+ oy (/ h2 2.0))
      0.0
    )
  )

  ;; Create block definition at origin 0,0,0
  (setq blkDef
    (vla-Add blks
      (vlax-3d-point '(0.0 0.0 0.0))
      bname
    )
  )

  ;; Outer border rectangle
  (_add-pline blkDef
    (list
      (list ox oy)
      (list (+ ox totalW) oy)
      (list (+ ox totalW) (+ oy totalH))
      (list ox (+ oy totalH))
    )
    T lname
  )

  ;; Horizontal divider between title and data rows
  (_add-line blkDef
    (list ox ydiv 0.0)
    (list (+ ox totalW) ydiv 0.0)
    lname
  )

  ;; Vertical divider between DWG No and Month
  (_add-line blkDef
    (list xdiv1 oy 0.0)
    (list xdiv1 ydiv 0.0)
    lname
  )

  ;; Vertical divider between Month and Year
  (_add-line blkDef
    (list xdiv2 oy 0.0)
    (list xdiv2 ydiv 0.0)
    lname
  )

  ;; Static text labels
  (_add-mtext blkDef cTitle "\\LDWG NO\\l" ht lname)
  (_add-mtext blkDef cMo    moStr           ht lname)
  (_add-mtext blkDef cYr    yrStr           ht lname)

  ;; Attribute definition for drawing number
  (_add-attdef blkDef cNo ht "DWGNO" noStr lname)

  (list totalW totalH)
)

;;; ================================================================
;;; MAIN COMMAND - DN
;;; Pick point = CENTER of box
;;; inspt is calculated by subtracting half totalW and half totalH
;;; so the picked point always lands at the exact centre
;;; ================================================================

(defun c:dn
       (/ cpt ht lname
          my noStr moStr yrStr
          tsz totalW totalH inspt
          doc spc insObj atts defht
          w1pad w2pad w3pad offy)

  (setq lname "A_Dwgblock")
  (_make-layer lname 35)

  ;;--------------------------------------------------------------
  ;; PROMPT CORRECTED:
  ;; Tells user clearly that the picked point = CENTER of box
  ;;--------------------------------------------------------------
  (setq cpt
    (getpoint "\nPick CENTER point of Drawing Number box: ")
  )

  (if cpt
    (progn
      ;; Text height based on drawing units
      (setq defht (_default-text-height))
      (setq ht
        (getreal
          (strcat "\nText height <" (rtos defht 2 2) ">: ")
        )
      )
      (if (null ht) (setq ht defht))

      ;;----------------------------------------------------------
      ;; PADDING - fixed values, independent of text height
      ;; Change these numbers to adjust each column gap
      ;;
      ;; w1pad = total left+right gap in Drawing Number column
      ;; w2pad = total left+right gap in Month column
      ;; w3pad = total left+right gap in Year column
      ;; offy  = total top+bottom gap in all rows
      ;;
      ;; Metric  (ht=0.23) : 0.01 gives small neat gap
      ;; Ft/In   (ht=9.0)  : increase to 0.5 or more
      ;;----------------------------------------------------------
      (setq w1pad 0.01)
      (setq w2pad 0.01)
      (setq w3pad 0.01)
      (setq offy  0.05)

      (vla-StartUndoMark (_doc))

      (setq my    (_month-year))
      (setq noStr (_dwg-no))
      (setq moStr (car  my))
      (setq yrStr (cadr my))

      ;; Print current settings
      (princ "\n------------------------------------------")
      (if (_is-feet-inches)
        (progn
          (princ "\nUnit mode  : FEET/INCHES")
          (princ "\nPrefix     : M")
        )
        (progn
          (princ "\nUnit mode  : METRIC/METER")
          (princ "\nPrefix     : (none)")
        )
      )
      (princ (strcat "\nText height: " (rtos ht    2 4)))
      (princ (strcat "\nw1pad      : " (rtos w1pad 2 4) "  (DWG No column padding)"))
      (princ (strcat "\nw2pad      : " (rtos w2pad 2 4) "  (Month  column padding)"))
      (princ (strcat "\nw3pad      : " (rtos w3pad 2 4) "  (Year   column padding)"))
      (princ (strcat "\noffy       : " (rtos offy  2 4) "  (row vertical  padding)"))
      (princ "\n------------------------------------------")

      ;; Build block definition
      (setq tsz
        (_build-block
          *dwg-blockname*
          ht w1pad w2pad w3pad offy
          noStr moStr yrStr
          lname
        )
      )
      (setq totalW (car  tsz))
      (setq totalH (cadr tsz))

      ;;----------------------------------------------------------
      ;; INSERT POINT CALCULATION
      ;; Picked point = CENTER of box
      ;; Subtract half width  → left  edge X
      ;; Subtract half height → bottom edge Y
      ;;----------------------------------------------------------
      (setq inspt
        (list
          (- (car  cpt) (/ totalW 2.0))   ; left   edge
          (- (cadr cpt) (/ totalH 2.0))   ; bottom edge
          0.0
        )
      )

      (setq doc (_doc))
      (setq spc (_space doc))

      ;; Insert block reference into drawing
      (setq insObj
        (vla-InsertBlock spc
          (vlax-3d-point inspt)
          *dwg-blockname*
          1.0 1.0 1.0 0.0
        )
      )
      (_set-common-props insObj lname)

      ;; Set attribute value
      (setq atts
        (vl-catch-all-apply
          'vlax-invoke (list insObj 'GetAttributes)
        )
      )
      (if (not (vl-catch-all-error-p atts))
        (foreach att atts
          (if (= (strcase (vla-get-TagString att)) "DWGNO")
            (progn
              (vla-put-TextString att noStr)
              (vla-Update att)
            )
          )
        )
        (princ "\nWARNING: attribute not set.")
      )

      (vla-EndUndoMark (_doc))
      (vl-catch-all-apply
        '(lambda () (command "_.REGEN"))
      )
      (princ
        (strcat "\nDrawing Number box placed. Center = picked point.")
      )
      (princ
        (strcat "\nDrawing no = " noStr)
      )
    )
    (princ "\nCancelled - no point selected.")
  )
  (princ)
)

;;; ================================================================
;;; DNUPDATE COMMAND
;;; ================================================================

(defun c:dnupdate (/ no unitmode)
  (setq no       (_dwg-no))
  (setq unitmode
    (if (_is-feet-inches) "FEET/INCHES" "METRIC/METER")
  )
  (princ "\n------------------------------------------")
  (princ (strcat "\nUnit mode  : " unitmode))
  (princ (strcat "\nUpdating to: " no))
  (princ "\n------------------------------------------")
  (_update-all-blocks)
  (princ "\nDNUPDATE complete.")
  (princ)
)

;;; ================================================================
;;; DNEDIT COMMAND (reserved - uncomment to enable)
;;; ================================================================

;;;(defun c:dnedit (/ en obj bname atts newval)
;;;  (setq en
;;;    (car (entsel "\nSelect Drawing Number to edit: "))
;;;  )
;;;  (if en
;;;    (progn
;;;      (setq bname (cdr (assoc 2 (entget en))))
;;;      (if (= bname *dwg-blockname*)
;;;        (progn
;;;          (setq obj  (vlax-ename->vla-object en))
;;;          (setq atts
;;;            (vl-catch-all-apply
;;;              'vlax-invoke (list obj 'GetAttributes)
;;;            )
;;;          )
;;;          (if (not (vl-catch-all-error-p atts))
;;;            (foreach att atts
;;;              (if (= (strcase (vla-get-TagString att))
;;;                     "DWGNO")
;;;                (progn
;;;                  (setq newval
;;;                    (getstring
;;;                      (strcat
;;;                        "\nNew drawing number <"
;;;                        (vla-get-TextString att)
;;;                        ">: "
;;;                      )
;;;                    )
;;;                  )
;;;                  (if (and newval (/= newval ""))
;;;                    (progn
;;;                      (vla-put-TextString att newval)
;;;                      (vla-Update att)
;;;                      (princ
;;;                        (strcat "\nUpdated to: " newval)
;;;                      )
;;;                    )
;;;                    (princ "\nNo change made.")
;;;                  )
;;;                )
;;;              )
;;;            )
;;;            (princ "\nERROR: could not read attributes.")
;;;          )
;;;        )
;;;        (princ "\nSelected object is not a DWG box.")
;;;      )
;;;    )
;;;    (princ "\nNo object selected.")
;;;  )
;;;  (vl-catch-all-apply
;;;    '(lambda () (command "_.REGEN"))
;;;  )
;;;  (princ)
;;;)

;;; ================================================================
;;; STARTUP
;;; ================================================================

(_make-reactor)
(princ "\n==================================================")
(princ "\n  DWG SMART BOX loaded successfully")
(princ "\n  Type DN        -> Insert Drawing Number box")
(princ "\n                    Pick point = CENTER of box")
(princ "\n  Type DNUPDATE  -> Refresh all Drawing Numbers")
(princ "\n--------------------------------------------------")
(princ "\n  UNIT DETECTION : INSUNITS + LUNITS (both)")
(princ "\n  Meter          : Height=0.23 | No prefix")
(princ "\n  Feet/Inches    : Height=9.0  | Prefix M")
(princ "\n--------------------------------------------------")
(princ "\n  PADDING (fixed setq values in c:dn)")
(princ "\n  w1pad = DWG No column  left+right gap")
(princ "\n  w2pad = Month column   left+right gap")
(princ "\n  w3pad = Year column    left+right gap")
(princ "\n  offy  = all rows       top+bottom gap")
(princ "\n==================================================")
(princ)